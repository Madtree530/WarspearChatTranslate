# -*- coding: utf-8 -*-
"""Warspear Online 聊天翻译器 —— 独立窗口 + OCR，不依赖 Ollama / 本地模型。
运行: python wptrans.py          (双击 run.bat)
自检: python wptrans.py --selftest
"""
from __future__ import annotations

import json, os, queue, re, sys, threading, time
import http.cookiejar, urllib.error, urllib.parse, urllib.request
from collections import OrderedDict
import tkinter as tk
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "config.json")
GLOSSARY_FILE = os.path.join(HERE, "glossary.json")

TARGET = "zh-CN"
SRC_LANGS = ["en", "ko", "fi", "vi", "pt", "ru", "th"]  # +泰语
EMOTE_TOKEN = "【表情】"

# ── 内置游戏黑话（用户 glossary.json 可覆盖同名键）──────────
BUILTIN_JARGON = {
    "wts": "出售", "wtb": "求购", "wtt": "求换", "wte": "求交换",
    "lfp": "组队", "lfs": "单刷", "lfp2": "组满2人", "lfp3": "组满3人",
    "pm": "私聊", "lf": "找", "mep": "带",
    "sign": "不朽符号", "signs": "不朽符号",
    "dmg 1": "一级武器强化材料", "dmg 2": "二级武器强化材料",
    "dmg 3": "三级武器强化材料", "dmg3": "三级武器强化材料",
    "def 1": "一级防具强化材料", "def 2": "二级防具强化材料",
    "def 3": "三级防具强化材料", "def3": "三级防具强化材料",
    "tpt": "TPT", "adv": "分支", "wz": "附魔武器",
    "ws": "附魔盾", "wc": "附魔头盔",
    "tech": "附魔", "hero": "英雄装备",
    "slot": "位置", "slots": "位置", "last slot": "最后位置",
    "sw": "匕首", "sd": "单手剑", "ss": "双手剑", "sorc": "法杖",
    "staff": "法杖", "bow": "弓", "bowg": "弓", "wand": "魔杖",
    "helm": "头盔", "helmet": "头盔", "boots": "靴子", "gloves": "手套",
    "cloak": "披风", "necklace": "项链", "ring": "戒指", "chest": "宝箱",
    "blow": "图腾", "totem": "图腾", "orb": "宝珠", "phoenix": "凤凰剑",
    "armor": "护甲", "armour": "护甲", "sh": "盾",
    "wep": "武器", "weapon": "武器", "spear": "长矛", "dagger": "匕首",
    "hammer": "锤", "axe": "斧", "chaos": "混沌",
    "scroll": "卷轴", "scrolls": "卷轴",
    "plz": "请", "pls": "请", "thx": "谢了", "ty": "谢谢",
    "wp": "打得不错", "wpe": "打得不错", "gg": "打完了", "bj": "拜",
    "gz": "恭喜",
    "sell": "出售", "buy": "求购", "trade": "交易",
    "tank": "坦克", "healer": "奶妈", "bard": "吟游诗人",
    "mage": "法师", "cleric": "牧师", "archer": "弓箭手",
    "warrior": "战士", "hunter": "猎人", "rogue": "盗贼",
    "necromancer": "死灵法师", "paladin": "圣骑士", "dwarf": "矮人",
}
POST = {
    "最后插槽": "最后位置", "插槽": "位置", "技术": "附魔",
    "私信我": "私聊我", "私信": "私聊",
}

# 运行时合并表（内置 + 用户，用户优先）
JARGON: dict = dict(BUILTIN_JARGON)
USER_GLOSSARY: dict = {}
_TERM_SUB = None
_jargon_lock = threading.Lock()

CACHE: OrderedDict = OrderedDict()       # 原文 body -> 译文
CACHE_NORM: OrderedDict = OrderedDict()  # norm_key -> 译文
CACHE_MAX = 768
LAST_CALL = 0.0
API_FAIL = [0]
_RATE_LOCK = threading.Lock()
MIN_INTERVAL = 1.2
_preferred_host = [None]

# ── 语种门控 ────────────────────────────────────────────────
_SKIP = re.compile(r"[ぁ-ヿ㐀-鿿]")
_CJK = re.compile(r"[㐀-鿿]")
_LETTER = re.compile(r"[A-Za-zÀ-ỿЀ-ӿ가-힣\u0E00-\u0E7F]")  # +Thai
_HANGUL = re.compile(r"[가-힣]")
_THAI = re.compile(r"[\u0E00-\u0E7F]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_VIET = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩị"
    r"òóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    r"ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊ"
    r"ÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)
_NAME_HEAD = (
    "A-Za-z0-9"
    "\u4e00-\u9fff"            # CJK
    "\uac00-\ud7a3"            # Hangul
    "\u0400-\u052f"           # Cyrillic，包括识别器可能输出的 і / һ 等
    "\u0e00-\u0e7f"            # Thai
    "À-ÖØ-öø-ÿĂÂÊÔƠƯăâêôơưĐđ"
)
_CHAT_PREFIX = re.compile(
    rf"^([{_NAME_HEAD}][{_NAME_HEAD}_\-']{{0,23}})\s*[:：]\s*(.+)$"
)
# 聊天线形：必须有「名字: 内容」；纯名字/公会飘字直接丢
_CHAT_LINE_OK = re.compile(
    rf"^[{_NAME_HEAD}][{_NAME_HEAD}_\-']{{0,23}}\s*[:：]\s*\S"
)
_SYSTEM_PREFIX = re.compile(
    r"^\s*[【\[（(]?\s*(?:信\s*息|系\s*统(?:\s*消\s*息)?|公\s*告|提\s*示)"
    r"\s*[】\]）)]?\s*[:：]"
)
_NAME_ONLY = re.compile(
    rf"^[{_NAME_HEAD}][{_NAME_HEAD}_\-']{{0,23}}\s*[:：]?\s*$"
)
_JUNK = re.compile(r"^[a-z]{1,5}$", re.I)
_NORM_KEEP = re.compile(r"[^\w\u4e00-\u9fff가-힣а-яА-Я\u0E00-\u0E7F]+", re.U)

# 表情 / OCR 噪声：Unicode 表情、私用区、常见乱码图符
_EMOJI_UNICODE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"  # Misc symbols & pictographs / emoticons / etc
    "\U0001FA00-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U0000FE00-\U0000FE0F"
    "\U0001F000-\U0001F02F"
    "\U000E0000-\U000E007F"
    "]+",
    flags=re.UNICODE,
)
_PUA = re.compile(r"[\uE000-\uF8FF\U000F0000-\U000FFFFD]+")
# OCR 常把小图标读成奇怪短串：纯符号、或 1–2 个非常见字母夹杂方块
_EMOTE_NOISE = re.compile(
    "(?:□|■|▪|▫|●|○|◆|◇|★★|☆|※|¤|\ufffd+"
    r"|[\u25A0-\u25FF]{1,4}"
    r"|[\u2190-\u21FF]{1,3}"
    r"|[\u2300-\u23FF]{1,3}"
    r")"
)

# 整段几乎只有噪声、无实质字母/汉字
_ONLY_NOISE = re.compile(
    r"^[\s\W\d□■▪▫●○◆◇★☆※¤�\u25A0-\u25FF\u2190-\u21FF\u2300-\u23FF"
    r"\U0001F300-\U0001FAFF\uE000-\uF8FF]+$",
    re.UNICODE,
)


def rebuild_jargon():
    """合并内置 + 用户词表，重建整词正则。用户同名覆盖内置。"""
    global JARGON, _TERM_SUB
    with _jargon_lock:
        merged = dict(BUILTIN_JARGON)
        for k, v in USER_GLOSSARY.items():
            key = str(k).strip().lower()
            val = str(v).strip()
            if key and val:
                merged[key] = val
        JARGON = merged
        _TERM_SUB = None


def load_user_glossary() -> dict:
    global USER_GLOSSARY
    try:
        with open(GLOSSARY_FILE, encoding="utf-8") as f:
            d = json.load(f)
        terms = d.get("terms", d) if isinstance(d, dict) else {}
        USER_GLOSSARY = {
            str(k).strip().lower(): str(v).strip()
            for k, v in terms.items()
            if str(k).strip() and str(v).strip()
        }
    except FileNotFoundError:
        USER_GLOSSARY = {}
        save_user_glossary()
    except Exception:
        USER_GLOSSARY = {}
    rebuild_jargon()
    return USER_GLOSSARY


def save_user_glossary():
    data = {
        "version": 1,
        "note": "用户自定义游戏术语。键=原文(小写)，值=中文。同名覆盖内置词表。",
        "terms": dict(sorted(USER_GLOSSARY.items())),
    }
    with open(GLOSSARY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def set_user_term(term: str, zh: str) -> str:
    """添加/更新用户词。返回规范化 key。清空缓存相关项。"""
    key = re.sub(r"\s+", " ", term.strip().lower())
    val = zh.strip()
    if not key or not val:
        raise ValueError("原文和译文都不能为空")
    if key in ("and", "or", "the", "a", "an", "to", "for", "of", "in", "on"):
        raise ValueError(f"拒绝收录普通连接词: {key}")
    USER_GLOSSARY[key] = val
    save_user_glossary()
    rebuild_jargon()
    CACHE.clear()
    CACHE_NORM.clear()
    return key


def delete_user_term(term: str) -> bool:
    key = re.sub(r"\s+", " ", term.strip().lower())
    if key in USER_GLOSSARY:
        del USER_GLOSSARY[key]
        save_user_glossary()
        rebuild_jargon()
        CACHE.clear()
        CACHE_NORM.clear()
        return True
    return False


def is_system_message(text: str) -> bool:
    """系统消息标签不属于玩家名：强化公告、上线提示等直接忽略。"""
    return bool(_SYSTEM_PREFIX.match(text or ""))


def need_translate(text: str) -> bool:
    # 去掉表情占位后再判断，避免 【表情】 触发跳过逻辑误伤
    t = text.replace(EMOTE_TOKEN, " ").strip()
    if not t:
        return False
    # 俄语中夹汉字（词表提示或 OCR 噪声）仍需翻译，不能跳过整句。
    return bool(_LETTER.search(t)) and (
        bool(_CYRILLIC.search(t)) or not bool(_SKIP.search(t)))


def detect_from_lang(text: str) -> str:
    if _HANGUL.search(text):
        return "ko"
    if _CYRILLIC.search(text):
        return "ru"
    if _THAI.search(text):
        return "th"
    if _VIET.search(text):
        return "vi"
    return "en"


def glossary_hit(text: str):
    key = re.sub(r"[\s,.!?]+$", "", text.strip().lower())
    # 纯表情行
    if key.replace(EMOTE_TOKEN.lower(), "").strip() == "" and EMOTE_TOKEN in text:
        return EMOTE_TOKEN
    return JARGON.get(key)


def split_speaker(line: str):
    m = _CHAT_PREFIX.match(line.strip())
    if m and m.group(2).strip():
        return m.group(1), m.group(2).strip()
    return "", line.strip()


def _term_re():
    global _TERM_SUB
    with _jargon_lock:
        if _TERM_SUB is None:
            words = sorted((w for w in JARGON if " " in w), key=len, reverse=True)
            singles = sorted((w for w in JARGON if " " not in w), key=len, reverse=True)
            parts = words + singles
            if not parts:
                _TERM_SUB = re.compile(r"(?!)")  # never matches
            else:
                _TERM_SUB = re.compile(
                    r"\b(" + "|".join(re.escape(w) for w in parts) + r")\b",
                    re.I)
        return _TERM_SUB


def apply_terms(text: str) -> str:
    return _term_re().sub(lambda m: JARGON.get(m.group(0).lower(), m.group(0)), text)


def post_fix(text: str) -> str:
    for wrong, right in sorted(POST.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(wrong, right)
    return text


def norm_line(text: str) -> str:
    s = re.sub(r"\s+", " ", text.strip().lower())
    s = s.replace(EMOTE_TOKEN, "")
    return _NORM_KEEP.sub("", s)


def normalize_emotes(text: str) -> str:
    """把表情/图标 OCR 噪声统一成 【表情】，避免 Bing 乱猜。"""
    if not text:
        return text
    s = _EMOJI_UNICODE.sub(f" {EMOTE_TOKEN} ", text)
    s = _PUA.sub(f" {EMOTE_TOKEN} ", s)
    s = _EMOTE_NOISE.sub(f" {EMOTE_TOKEN} ", s)
    # 连续多个表情合并为一个
    s = re.sub(rf"(?:\s*{re.escape(EMOTE_TOKEN)}\s*)+", f" {EMOTE_TOKEN} ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_emote_only(text: str) -> bool:
    t = text.replace(EMOTE_TOKEN, "").strip()
    if not t:
        return True
    return bool(_ONLY_NOISE.match(t)) and not bool(_LETTER.search(t))


def similar_key(a: str, b: str) -> bool:
    """近似重复（OCR 抖动）：长度接近且编辑距离很小。"""
    if not a or not b:
        return False
    if a == b:
        return True
    if abs(len(a) - len(b)) > 2:
        return False
    # 简单 Hamming/子串：短串用包含；长串算不等字符比例
    if len(a) <= 4 or len(b) <= 4:
        return a in b or b in a
    mism = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    return mism <= max(1, len(a) // 8)


# ── DPI / 显示器 ────────────────────────────────────────────
def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        ctypes = __import__("ctypes")
        ctypes.windll.user32.SetProcessDpiAwarenessContext(__import__("ctypes").c_void_p(-4))
        return
    except Exception:
        pass
    try:
        __import__("ctypes").windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def display_profile() -> dict:
    dpi, mon = 96, (0, 0, 1920, 1080)
    if sys.platform != "win32":
        return {"dpi": dpi, "monitor": list(mon)}
    ctypes = __import__("ctypes")
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    try:
        dpi = int(user32.GetDpiForSystem())
    except Exception:
        dpi = 96
    try:
        l = user32.GetSystemMetrics(76)
        t = user32.GetSystemMetrics(77)
        w = user32.GetSystemMetrics(78)
        h = user32.GetSystemMetrics(79)
        if w > 0 and h > 0:
            mon = (l, t, l + w, t + h)
        else:
            mon = (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    except Exception:
        pass
    try:
        shcore = ctypes.windll.shcore
        mons = []

        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                            ctypes.POINTER(wt.RECT), ctypes.c_double)
        def _cb(hmon, hdc, lprect, lparam):
            r = lprect.contents
            dx = ctypes.c_uint(96)
            dy = ctypes.c_uint(96)
            try:
                shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy))
            except Exception:
                pass
            mons.append((r.left, r.top, r.right, r.bottom, int(dx.value)))
            return 1

        user32.EnumDisplayMonitors(0, 0, _cb, 0)
        if mons:
            primary = next(
                (m for m in mons if m[0] <= 0 <= m[2] and m[1] <= 0 <= m[3]),
                mons[0])
            mon = primary[:4]
            dpi = primary[4] or dpi
    except Exception:
        pass
    return {"dpi": int(dpi or 96), "monitor": list(mon)}


def scale_region(region, old_dpi, new_dpi, old_mon=None, new_mon=None):
    if not region or len(region) != 4:
        return None
    x, y, w, h = [int(v) for v in region]
    od, nd = max(1, int(old_dpi or 96)), max(1, int(new_dpi or 96))
    if od != nd:
        s = nd / od
        x, y, w, h = int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s))
    if old_mon and new_mon and len(old_mon) == 4 and len(new_mon) == 4:
        dx = int(new_mon[0]) - int(old_mon[0])
        dy = int(new_mon[1]) - int(old_mon[1])
        ow = max(1, int(old_mon[2]) - int(old_mon[0]))
        oh = max(1, int(old_mon[3]) - int(old_mon[1]))
        nw = max(1, int(new_mon[2]) - int(new_mon[0]))
        nh = max(1, int(new_mon[3]) - int(new_mon[1]))
        if abs(nw / ow - nd / od) < 0.15 and abs(nh / oh - nd / od) < 0.15:
            x += dx
            y += dy
    return (x, y, w, h)


# ── Bing ────────────────────────────────────────────────────
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
_BING_HOSTS = ("cn.bing.com", "www.bing.com")
_bing_tok = [None, 0.0, None]
_tok_lock = threading.Lock()
_host_cooldown = {}
_host_lock = threading.Lock()
TOK_TTL = 1800
EMPTY_COOLDOWN = 120
RATE_COOLDOWN = 90


def _bing_opener():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _host_ready(host: str) -> bool:
    with _host_lock:
        return time.time() >= _host_cooldown.get(host, 0)


def _mark_host(host: str, seconds: float):
    with _host_lock:
        _host_cooldown[host] = time.time() + seconds


def _ordered_hosts():
    hosts = []
    pref = _preferred_host[0]
    if pref and pref in _BING_HOSTS and _host_ready(pref):
        hosts.append(pref)
    for h in _BING_HOSTS:
        if h not in hosts and _host_ready(h):
            hosts.append(h)
    return hosts or list(_BING_HOSTS)


def bing_token(force=False, only_host=None):
    now = time.time()
    with _tok_lock:
        if (not force and not only_host and _bing_tok[0]
                and now - _bing_tok[1] < TOK_TTL and _bing_tok[2] is not None):
            if _host_ready(_bing_tok[0][4]):
                return _bing_tok[0]
        hosts = [only_host] if only_host else _ordered_hosts()
        last_err = None
        for host in hosts:
            opener = _bing_opener()
            req = urllib.request.Request(f"https://{host}/translator", headers=UA)
            try:
                html = opener.open(req, timeout=20).read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                last_err = RuntimeError(f"token HTTP{e.code}@{host}")
                if e.code in (429, 503):
                    _mark_host(host, RATE_COOLDOWN)
                continue
            except urllib.error.URLError as e:
                last_err = RuntimeError(f"token 网络@{host}: {e.reason}")
                _mark_host(host, 30)
                continue
            ig = re.search(r'IG:"([^"]+)"', html)
            iid = re.search(r"(IIDAb[A-Za-z0-9+/=]{20,})", html)
            ab = re.search(
                r'params_AbusePreventionHelper\s*=\s*\[\s*(\d+)\s*,\s*"([^"]+)"',
                html)
            if not (ig and iid and ab):
                last_err = RuntimeError(f"token 解析失败@{host}")
                _mark_host(host, 60)
                continue
            tok = (ig.group(1), iid.group(1), int(ab.group(1)), ab.group(2), host)
            _bing_tok[0], _bing_tok[1], _bing_tok[2] = tok, now, opener
            return tok
        raise last_err or RuntimeError("Bing token 全部失败")


def bing_translate(text: str, sl: str) -> str:
    last_err = None
    for host in _ordered_hosts():
        try:
            ig, iid, ts, key, used = bing_token(force=True, only_host=host)
        except Exception as e:
            last_err = e
            continue
        opener = _bing_tok[2]
        url = f"https://{used}/ttranslatev3?isVertical=1&IG={ig}&IID={iid}"
        body = urllib.parse.urlencode({
            "fromLang": sl, "text": text, "to": "zh-Hans",
            "token": key, "key": ts,
            "tryFetchingGenderDebiasedTranslations": "true"}).encode()
        req = urllib.request.Request(
            url,
            headers=dict(UA, **{
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"https://{used}/translator",
                "Origin": f"https://{used}"}),
            data=body)
        try:
            r = opener.open(req, timeout=15)
        except urllib.error.HTTPError as e:
            last_err = RuntimeError(f"HTTP{e.code}@{used}")
            if e.code in (401, 403):
                with _tok_lock:
                    _bing_tok[0] = None
                _mark_host(used, 20)
            elif e.code == 429:
                _mark_host(used, RATE_COOLDOWN)
            else:
                _mark_host(used, 45)
            continue
        except urllib.error.URLError as e:
            last_err = RuntimeError(f"网络@{used}: {e.reason}")
            _mark_host(used, 30)
            continue
        raw = r.read().decode("utf-8", "replace").strip()
        if not raw:
            last_err = RuntimeError(f"空响应@{used}")
            _mark_host(used, EMPTY_COOLDOWN)
            with _tok_lock:
                if _bing_tok[0] and _bing_tok[0][4] == used:
                    _bing_tok[0] = None
            continue
        try:
            d = json.loads(raw)
            out = next(t["text"] for t in d[0]["translations"]
                       if t.get("to") in ("zh-Hans", "zh-CN", "zh"))
            if not isinstance(out, str) or not out.strip():
                raise ValueError("空译文")
            if sl == "ru" and _CYRILLIC.search(out) and (
                    not _CJK.search(out) or norm_line(out) == norm_line(text)):
                raise ValueError("俄语译文未返回中文")
            _preferred_host[0] = used  # 粘性成功线路
            return out
        except (KeyError, IndexError, TypeError, ValueError, StopIteration) as e:
            reason = str(e) if isinstance(e, ValueError) else "响应异常"
            last_err = RuntimeError(f"{reason}@{used}")
            _mark_host(used, 45)
            continue
    raise last_err or RuntimeError("Bing 翻译失败")


def _cache_put(body: str, out: str):
    CACHE[body] = out
    CACHE.move_to_end(body)
    nk = norm_line(body)
    if nk:
        CACHE_NORM[nk] = out
        CACHE_NORM.move_to_end(nk)
    while len(CACHE) > CACHE_MAX:
        CACHE.popitem(last=False)
    while len(CACHE_NORM) > CACHE_MAX:
        CACHE_NORM.popitem(last=False)


def _cache_get(body: str):
    if body in CACHE:
        CACHE.move_to_end(body)
        return CACHE[body]
    nk = norm_line(body)
    if nk and nk in CACHE_NORM:
        CACHE_NORM.move_to_end(nk)
        return CACHE_NORM[nk]
    # 模糊命中：OCR 差 1–2 字符
    if nk:
        for k, v in list(CACHE_NORM.items())[-80:]:
            if similar_key(nk, k):
                return v
    return None


def translate(text: str) -> str:
    text = normalize_emotes(text.strip())
    if not text or is_system_message(text):
        return ""
    if is_emote_only(text):
        return EMOTE_TOKEN
    if not need_translate(text):
        # 已是中文但可能夹表情：直接回显规范化后的文本
        if EMOTE_TOKEN in text and _SKIP.search(text):
            return text
        return ""

    hit = glossary_hit(text)
    if hit:
        return hit

    speaker, body = split_speaker(text)
    body = normalize_emotes(body)
    if is_emote_only(body):
        out = EMOTE_TOKEN
        return f"{speaker}: {out}" if speaker else out
    if _JUNK.match(body) and body.lower() not in JARGON:
        return ""
    if not need_translate(body):
        return ""
    hit = glossary_hit(body)
    if hit:
        return f"{speaker}: {hit}" if speaker else hit

    cached = _cache_get(body)
    if cached is not None:
        return f"{speaker}: {cached}" if speaker else cached

    # 送翻前：表情占位保留，术语替换；把 【表情】 临时换成安全标记防 Bing 乱改
    hinted = apply_terms(body)
    emote_mark = "⟦EMOTE⟧"
    hinted_api = hinted.replace(EMOTE_TOKEN, emote_mark)

    if not need_translate(hinted.replace(EMOTE_TOKEN, " ")):
        out = hinted
        _cache_put(body, out)
        return f"{speaker}: {out}" if speaker else out

    global LAST_CALL
    with _RATE_LOCK:
        wait = MIN_INTERVAL - (time.time() - LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        LAST_CALL = time.time()

    last_err = None
    for attempt in range(2):
        try:
            # 送 API 时去掉表情标记，译后再拼回 —— 更稳
            api_text = re.sub(rf"\s*{re.escape(emote_mark)}\s*", " ", hinted_api).strip()
            api_text = re.sub(r"\s+", " ", api_text)
            if not api_text or not need_translate(api_text):
                out = hinted
            else:
                raw_zh = post_fix(bing_translate(api_text, detect_from_lang(api_text)))
                # 若原文有表情，译文末尾/相应位置补回
                if EMOTE_TOKEN in hinted and EMOTE_TOKEN not in raw_zh:
                    out = f"{raw_zh} {EMOTE_TOKEN}".strip()
                else:
                    out = raw_zh
            _cache_put(body, out)
            return f"{speaker}: {out}" if speaker else out
        except Exception as e:
            last_err = e
            time.sleep(2.0 * (attempt + 1))
    API_FAIL[0] += 1
    msg = str(last_err) if last_err else "未知"
    if len(msg) > 48:
        msg = msg[:48] + "…"
    return f"[翻译失败: {msg}]"


# ── OCR ─────────────────────────────────────────────────────
_ocr_lock = threading.Lock()
_ocr = None       # 中英主引擎
_ocr_th = None    # 泰语仅识别，共用主引擎检测框
_ocr_ru = None    # 俄语仅识别；中英模型会把西里尔字母读成拉丁字母
_ocr_ru_error = ""
_chat_frame_cache = {}
_title_frame_cache = {}
OCR_REFRESH_SECONDS = 5.0
_ocr_frame_id = 0
MODELS_DIR = os.path.join(HERE, "models")
TH_REC_ONNX = os.path.join(MODELS_DIR, "th_PP-OCRv5_rec_mobile.onnx")
TH_REC_DICT = os.path.join(MODELS_DIR, "ppocrv5_th_dict.txt")
RU_REC_ONNX = os.path.join(MODELS_DIR, "cyrillic_PP-OCRv5_rec_mobile.onnx")
RU_REC_DICT = os.path.join(MODELS_DIR, "ppocrv5_cyrillic_dict.txt")
_HAS_SCRIPT = re.compile(
    r"[A-Za-z가-힣一-鿿Ѐ-ӿà-ỹ\u0E00-\u0E7F]"
)


def np_array(img):
    import numpy as np
    return np.array(img)


def _ensure_thai_model():
    """首次需要时拉取泰语识别 onnx（已有则跳过）。"""
    os.makedirs(MODELS_DIR, exist_ok=True)
    urls = {
        TH_REC_ONNX: (
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/"
            "v3.10.0/onnx/PP-OCRv5/rec/th_PP-OCRv5_rec_mobile.onnx"),
        TH_REC_DICT: (
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/"
            "v3.10.0/paddle/PP-OCRv5/rec/th_PP-OCRv5_rec_mobile/ppocrv5_th_dict.txt"),
    }
    for path, url in urls.items():
        need = (not os.path.isfile(path)) or os.path.getsize(path) < 100
        if path.endswith(".onnx"):
            need = (not os.path.isfile(path)) or os.path.getsize(path) < 1_000_000
        if not need:
            continue
        try:
            urllib.request.urlretrieve(url, path)
        except Exception as e:
            raise RuntimeError(f"下载泰语 OCR 模型失败: {e}") from e


def _get_ocr_engines(include_thai=True):
    """单线程推理；泰语只建识别器，不再重复建检测/方向分类器。"""
    global _ocr, _ocr_th
    import cv2
    from rapidocr_onnxruntime import RapidOCR
    if _ocr is None:
        cv2.setNumThreads(1)
        _ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1,
                        use_cls=False, det_limit_type="max")
    if include_thai and _ocr_th is None:
        try:
            _ensure_thai_model()
            from rapidocr_onnxruntime.ch_ppocr_rec import TextRecognizer
            config = {"model_path": TH_REC_ONNX, "rec_batch_num": 6,
                      "rec_img_shape": [3, 48, 320],
                      "intra_op_num_threads": 1, "inter_op_num_threads": 1,
                      "use_cuda": False, "use_dml": False}
            if os.path.isfile(TH_REC_DICT) and os.path.getsize(TH_REC_DICT) > 50:
                config["rec_keys_path"] = TH_REC_DICT
            _ocr_th = TextRecognizer(config)
        except Exception:
            _ocr_th = False  # 标记不可用，避免反复尝试
    return _ocr, (_ocr_th if include_thai and _ocr_th not in (None, False) else None)


def _get_russian_recognizer():
    """按需加载俄语小模型，共用检测框且仅使用一个推理线程。"""
    global _ocr_ru
    if _ocr_ru is None:
        import hashlib
        from rapidocr_onnxruntime.ch_ppocr_rec import TextRecognizer
        os.makedirs(MODELS_DIR, exist_ok=True)
        base = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/"
        files = (
            (RU_REC_ONNX, "onnx/PP-OCRv5/rec/cyrillic_PP-OCRv5_rec_mobile.onnx",
             "90f761b4bfcce0c8c561c0cb5c887b0971d3ec01c32164bdf7374a35b0982711"),
            (RU_REC_DICT, "paddle/PP-OCRv5/rec/cyrillic_PP-OCRv5_rec_mobile/ppocrv5_cyrillic_dict.txt",
             "db40aa52ceb112055be80c694afdf655d5d2c4f7873704524cc16a447ca913ba"),
        )
        for path, suffix, digest in files:
            if os.path.isfile(path) and os.path.getsize(path) > 100:
                continue
            temporary = path + ".download"
            try:
                with urllib.request.urlopen(base + suffix, timeout=45) as response:
                    data = response.read()
                if hashlib.sha256(data).hexdigest() != digest:
                    raise RuntimeError("模型文件校验失败")
                with open(temporary, "wb") as target:
                    target.write(data)
                os.replace(temporary, path)
            except Exception as e:
                raise RuntimeError(f"下载俄语 OCR 模型失败: {e}") from e
            finally:
                if os.path.isfile(temporary):
                    os.remove(temporary)
        _ocr_ru = TextRecognizer({
            "model_path": RU_REC_ONNX, "rec_keys_path": RU_REC_DICT,
            "rec_batch_num": 6, "rec_img_shape": [3, 48, 320],
            "intra_op_num_threads": 1, "inter_op_num_threads": 1,
            "use_cuda": False, "use_dml": False,
        })
    return _ocr_ru


def preprocess_chat(img):
    """不按频道色过滤。只压掉很暗的底（透字），保留中高亮各色聊天字，再提对比。"""
    import numpy as np
    from PIL import Image, ImageOps, ImageEnhance, ImageFilter
    if min(img.size) < 1:
        return img
    rgb = img.convert("RGB")
    arr = np.asarray(rgb, dtype=np.float32)
    lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    # 仅抹掉很暗背景；勿用高分位阈值，否则框进亮 UI 时会误杀聊天字
    floor = min(42.0, max(28.0, float(np.percentile(lum, 20))))
    keep = lum >= floor
    out = arr.copy()
    out[~keep] = 0
    im = Image.fromarray(out.astype(np.uint8), mode="RGB")
    if im.height < 240 or im.width < 320:
        im = im.resize((im.width * 2, im.height * 2), resample=3)
    g = ImageOps.grayscale(im)
    g = ImageEnhance.Contrast(g).enhance(1.55)
    g = ImageEnhance.Sharpness(g).enhance(1.25)
    g = g.filter(ImageFilter.MedianFilter(size=3))
    return g.convert("RGB")


def _merge_line_boxes(items, y_tol=10):
    """items: (y, x, text, score, x1, x2) -> (y, text, x1, x2, n_parts)"""
    if not items:
        return []
    items = sorted(items, key=lambda t: (t[0], t[1]))
    groups, cur = [], [items[0]]
    for it in items[1:]:
        if abs(it[0] - cur[0][0]) <= y_tol:
            cur.append(it)
        else:
            groups.append(cur)
            cur = [it]
    groups.append(cur)
    lines = []
    for g in groups:
        g = sorted(g, key=lambda t: t[1])
        text = " ".join(t[2] for t in g)
        y = sum(t[0] for t in g) / len(g)
        x1 = min(t[4] if len(t) > 4 else t[1] for t in g)
        x2 = max(t[5] if len(t) > 5 else t[1] for t in g)
        lines.append((y, text, x1, x2, len(g)))
    return lines


def is_chat_shaped(text: str) -> bool:
    """只要像「名字: 内容」的聊天线；丢掉飘字/公会/纯名。"""
    t = text.strip()
    if not t or is_system_message(t):
        return False
    if t == EMOTE_TOKEN:
        return False
    if _NAME_ONLY.match(t):
        return False
    if _CHAT_LINE_OK.match(t):
        return True
    if _CHAT_PREFIX.match(t):
        return True
    return False


def filter_dense_chat_rows(lines, gap_factor=2.4, min_cluster=2):
    """空间过滤：保留垂直方向成簇的聊天线，丢掉稀疏飘字。行少时不过度丢弃。"""
    shaped = [(y, t, *rest) for y, t, *rest in lines if is_chat_shaped(t)]
    if len(lines) <= 3 or len(shaped) <= 2:
        return [t for _, t, *_ in shaped]
    ordered = sorted(lines, key=lambda r: r[0])
    ys = [r[0] for r in ordered]
    gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    gaps_pos = [g for g in gaps if g > 1]
    if not gaps_pos:
        return [t for _, t, *_ in ordered if is_chat_shaped(t)]
    gaps_pos.sort()
    median = gaps_pos[len(gaps_pos) // 2]
    thr = max(18.0, median * gap_factor)
    clusters, cur = [], [0]
    for i, g in enumerate(gaps):
        if g <= thr:
            cur.append(i + 1)
        else:
            clusters.append(cur)
            cur = [i + 1]
    clusters.append(cur)
    keep_idx = set()
    big = [c for c in clusters if len(c) >= min_cluster]
    if not big:
        big = [max(clusters, key=len)]
    for c in big:
        keep_idx.update(c)
    out = []
    for i, row in enumerate(ordered):
        if i not in keep_idx:
            continue
        text = row[1]
        if is_chat_shaped(text):
            out.append(text)
    return out


def _parse_ocr_result(result, min_len=2):
    items = []
    for box, text, score in result or []:
        # 含泰文时略放宽置信度
        min_score = 0.45 if _THAI.search(text or "") else 0.55
        if score < min_score:
            continue
        text = normalize_emotes((text or "").strip())
        if len(text) < min_len and text != EMOTE_TOKEN:
            continue
        if text != EMOTE_TOKEN and not _HAS_SCRIPT.search(text) and EMOTE_TOKEN not in text:
            continue
        y = float(box[0][1])
        x = float(box[0][0])
        try:
            x2 = float(box[1][0])
            bh = abs(float(box[2][1]) - float(box[0][1]))
            bw = abs(x2 - x)
            if max(bw, bh) < 28 and len(text) <= 3 and text.lower() not in JARGON:
                text = EMOTE_TOKEN
        except Exception:
            x2 = x
        items.append((y, x, text, float(score), x, x2))
    return items


def _reliable_thai_body(text, score):
    """泰语必须出现在正文；玩家名/图标里碰巧识出一个泰字不算。"""
    if score < 0.80 or is_system_message(text):
        return False
    _, body = split_speaker(text)
    thai_chars = len(_THAI.findall(body))
    letters = len(_LETTER.findall(body))
    return thai_chars >= 2 and thai_chars >= max(1, letters) * 0.20


def _prefer_thai_merge(ch_items, th_items, y_tol=14):
    """同一文字框比较可靠度，保护系统消息和可靠中文，避免泰语幻读覆盖。"""
    used_th = set()
    out = []
    for cy, cx, ct, cs, cx1, cx2 in ch_items:
        best = None
        best_i = None
        for i, (ty, tx, tt, ts, tx1, tx2) in enumerate(th_items):
            if i in used_th:
                continue
            if (abs(ty - cy) <= y_tol and abs(tx1 - cx1) <= y_tol
                    and abs(tx2 - cx2) <= y_tol):
                best, best_i = (ty, tx, tt, ts, tx1, tx2), i
                break
        if best is not None:
            # 即使不采用，也已与此框配对；不能再以“新增泰语行”绕过判断。
            used_th.add(best_i)
        if is_system_message(ct):
            # 留下位置供密行空间过滤使用；最终由 is_chat_shaped 排除文本。
            # 提前删掉会把夹在几条公告中间的真正玩家聊天当成离群行。
            out.append((cy, cx, ct, cs, cx1, cx2))
            continue
        protected_chinese = cs >= 0.90 and bool(_SKIP.search(ct))
        if (best is not None and not protected_chinese
                and _reliable_thai_body(best[2], best[3]) and best[3] >= cs + 0.02):
            out.append(best)
        else:
            out.append((cy, cx, ct, cs, cx1, cx2))
    # 主模型没读出来时，也要求正文中有可靠泰语。
    for i, row in enumerate(th_items):
        if i not in used_th and _reliable_thai_body(row[2], row[3]):
            out.append(row)
    return out


def _protected_chinese_body(text, score):
    _, body = split_speaker(text)
    # 单个误识别汉字不能压过真正的俄语正文。
    return is_system_message(text) or (score >= 0.90 and len(_CJK.findall(body)) >= 2)


def _reliable_russian_body(text, score, *, russian_frame=False):
    if score < 0.80 or is_system_message(text):
        return False
    _, body = split_speaker(text)
    count = len(_CYRILLIC.findall(body))
    letters = len(_LETTER.findall(body))
    # 单个西里尔字母只在已有多条可靠俄语聊天的画面中接受。
    minimum = 1 if russian_frame and score >= 0.85 else 2
    return count >= minimum and count >= max(1, letters) * 0.20


def _prefer_russian_merge(ch_items, ru_items, y_tol=14):
    eligible = [row for row in ch_items if not _protected_chinese_body(row[2], row[3])]
    strong = sum(_reliable_russian_body(row[2], row[3]) for row in ru_items)
    russian_frame = strong >= max(2, len(eligible) / 2)
    used, out = set(), []
    for primary in ch_items:
        cy, cx, ct, cs, cx1, cx2 = primary
        paired = None
        for i, candidate in enumerate(ru_items):
            ry, _, _, _, rx1, rx2 = candidate
            if i not in used and abs(ry - cy) <= y_tol and abs(rx1 - cx1) <= y_tol and abs(rx2 - cx2) <= y_tol:
                paired = candidate
                used.add(i)
                break
        if (paired is not None and not _protected_chinese_body(ct, cs)
                and _reliable_russian_body(paired[2], paired[3], russian_frame=russian_frame)):
            # 俄语模型适合正文；拉丁玩家名由主模型保留，避免变成俄文字母。
            speaker, _ = split_speaker(ct)
            _, body = split_speaker(paired[2])
            text = f"{speaker}: {body}" if speaker else paired[2]
            out.append((cy, cx, text, paired[3], cx1, cx2))
        else:
            out.append(primary)
    for i, candidate in enumerate(ru_items):
        if i not in used and _reliable_russian_body(candidate[2], candidate[3]):
            out.append(candidate)
    return out


def _capture_region(region):
    import mss
    from PIL import Image
    left, top, width, height = [int(v) for v in region]
    if width < 8 or height < 8:
        return None
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top,
                         "width": width, "height": height})
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _frame_matches(cache, region, pixels, min_len):
    # 精确比像素，单字符变化也会重识别；定期刷新避免永久缓存误识别。
    return (cache.get("region") == tuple(region)
            and cache.get("pixels") == pixels and cache.get("min_len") == min_len
            and time.monotonic() - cache.get("time", 0) < OCR_REFRESH_SECONDS)


def _ocr_chat_frame(region, min_len=2, *, force=False):
    """返回聊天行、原始文字框数、推理编号；缓存帧不能冒充第二次 OCR 确认。"""
    global _ocr_frame_id, _ocr_ru, _ocr_ru_error
    with _ocr_lock:
        img = _capture_region(region)
        if img is None:
            return [], 0, -1
        pixels = img.tobytes()
        if not force and _frame_matches(_chat_frame_cache, region, pixels, min_len):
            return _chat_frame_cache["value"]
        ocr_ch, _ = _get_ocr_engines(include_thai=False)
        arr = np_array(preprocess_chat(img))
        # 中英/泰语共享检测框和裁剪图，取消正向聊天文字不需要的方向分类。
        boxes, _ = ocr_ch(arr, use_rec=False, use_cls=False)
        boxes = boxes or []
        result_ch = []
        result_ru = []
        result_th = None
        if boxes:
            import numpy as np
            crops = ocr_ch.get_crop_img_list(arr, np.asarray(boxes, dtype=np.float32))
            rec_ch, _ = ocr_ch.text_rec(crops)
            result_ch = [[box, text, score] for box, (text, score) in zip(boxes, rec_ch)]
            # 中文公告不交给外语模型猜；其余文字框尝试西里尔字母识别。
            ru_indices = [i for i, (_, text, score) in enumerate(result_ch)
                          if not _protected_chinese_body(text, score)
                          and _LETTER.search(text) and not _HANGUL.search(text)
                          and not _THAI.search(text)]
            if ru_indices and _ocr_ru is not False:
                try:
                    rec_ru, _ = _get_russian_recognizer()([crops[i] for i in ru_indices])
                    result_ru = [[boxes[i], text, score]
                                 for i, (text, score) in zip(ru_indices, rec_ru)]
                except Exception as error:
                    # 俄语模型故障不能中断英文/泰语；本次运行禁用，重启后重试。
                    _ocr_ru = False
                    _ocr_ru_error = str(error)
        items_ch = _parse_ocr_result(result_ch, min_len=min_len)
        items_ru = _parse_ocr_result(result_ru, min_len=min_len)
        items = _prefer_russian_merge(items_ch, items_ru)
        # 已确认俄语的框不再跑泰语，避免叠加三套完整识别的 CPU 开销。
        resolved_ru = {(row[0], row[4], row[5]) for row in items
                       if _reliable_russian_body(row[2], row[3], russian_frame=True)}
        if boxes:
            thai_indices = [i for i, (box, text, score) in enumerate(result_ch)
                            if not _protected_chinese_body(text, score)
                            and (float(box[0][1]), float(box[0][0]), float(box[1][0])) not in resolved_ru]
            _, ocr_th = _get_ocr_engines(include_thai=bool(thai_indices))
            if ocr_th is not None and thai_indices:
                try:
                    rec_th, _ = ocr_th([crops[i] for i in thai_indices])
                    result_th = [[boxes[i], text, score]
                                 for i, (text, score) in zip(thai_indices, rec_th)]
                except Exception:
                    result_th = None
        items_th = _parse_ocr_result(result_th, min_len=min_len) if result_th else []
        items = _prefer_thai_merge(items, items_th)
        lines = filter_dense_chat_rows(_merge_line_boxes(items))
        _ocr_frame_id += 1
        value = (lines, len(boxes), _ocr_frame_id)
        _chat_frame_cache.update(region=tuple(region), pixels=pixels, min_len=min_len,
                                 time=time.monotonic(), value=value)
        return value


def ocr_lines(region, min_len=2):
    """region=(left,top,w,h) -> [聊天线, ...]，静止画面复用结果。"""
    return _ocr_chat_frame(region, min_len)[0]


def ocr_all_texts(region, min_len=1):
    """原始 OCR 文本（不做 Name:msg / 密行过滤），供频道标题检测。"""
    with _ocr_lock:
        img = _capture_region(region)
        if img is None:
            return []
        pixels = img.tobytes()
        if _frame_matches(_title_frame_cache, region, pixels, min_len):
            return _title_frame_cache["value"]
        ocr_ch, _ = _get_ocr_engines(include_thai=False)
        # 标题在顶栏，颜色可能是金色；用原图+轻度增强更稳
        from PIL import ImageEnhance, ImageOps
        g = ImageOps.grayscale(img)
        g = ImageEnhance.Contrast(g).enhance(1.6)
        arr = np_array(g.convert("RGB"))
        result_ch, _ = ocr_ch(arr, use_cls=False, text_score=0.4)
        texts = []
        for box, text, score in result_ch or []:
            if score < 0.4:
                continue
            text = (text or "").strip()
            if len(text) >= min_len:
                texts.append(text)
        _title_frame_cache.update(region=tuple(region), pixels=pixels, min_len=min_len,
                                  time=time.monotonic(), value=texts)
        return texts


def chat_title_region(region):
    """标题位于框选顶栏；智能模式只检测顶部小条，不扫描整屏聊天。"""
    left, top, width, height = region
    return left, top, width, min(height, max(96, min(224, int(height * 0.15))))




# ── 智能开停：聊天频道标题检测 ──────────────────────────────
CHAT_CHANNEL_TITLES = (
    "世界聊天", "交易聊天", "私密聊天", "队伍聊天", "区域聊天", "公会聊天",
)
# 不单独作为开停条件
CHAT_IGNORE_TABS = ("信息",)

# OCR 常见形近/噪声替换（仅用于标题匹配）
_CHANNEL_OCR_FIX = str.maketrans({
    " ": "", "　": "",
    "明": "聊", "卿": "聊", "朗": "聊",
    "畀": "界", "堺": "界",
})
_CHANNEL_NOISE_RE = re.compile(r"[\s\|\[\]【】\-_=+·•]+")


def normalize_channel_ocr(text: str) -> str:
    """压缩空白并修正常见 OCR 噪声，便于匹配四字频道名。"""
    if not text:
        return ""
    s = _CHANNEL_NOISE_RE.sub("", text.strip())
    s = s.translate(_CHANNEL_OCR_FIX)
    # 多字替换
    for a, b in (("交昜", "交易"), ("交昌", "交易"), ("私蜜", "私密"),
                 ("切队", "队伍"), ("区城", "区域"), ("公合", "公会"),
                 ("世畀", "世界"), ("卿天", "聊天"), ("明天", "聊天")):
        s = s.replace(a, b)
    return s


def _fuzzy_title_hit(blob: str, title: str, max_mismatch: int = 1) -> bool:
    """blob 中是否出现与 title 近似的连续四字（允许 1 字误差）。"""
    if title in blob:
        return True
    n = len(title)
    if len(blob) < n:
        # 短串整体比对
        if abs(len(blob) - n) <= 1 and sum(1 for a, b in zip(blob, title) if a != b) + abs(len(blob) - n) <= max_mismatch:
            return True
        return False
    for i in range(len(blob) - n + 1):
        window = blob[i:i + n]
        mism = sum(1 for a, b in zip(window, title) if a != b)
        if mism <= max_mismatch:
            return True
    return False


def detect_chat_channel(texts) -> str | None:
    """从 OCR 文本列表中识别当前聊天频道标题；信息页签不算。

    返回规范频道名，如「世界聊天」；未识别返回 None。
    """
    if isinstance(texts, str):
        texts = [texts]
    blobs = []
    for raw in texts or []:
        n = normalize_channel_ocr(raw)
        if not n:
            continue
        # 单独「信息」忽略
        if n in CHAT_IGNORE_TABS or n.startswith("信息:") or n.startswith("信息："):
            continue
        blobs.append(n)
        for title in CHAT_CHANNEL_TITLES:
            if _fuzzy_title_hit(n, title):
                return title
    # 拼接邻近碎片再试（OCR 有时拆开）
    joined = "".join(blobs)
    for title in CHAT_CHANNEL_TITLES:
        if _fuzzy_title_hit(joined, title):
            return title
    return None


def is_channel_title_line(text: str) -> bool:
    """整行就是频道标题时，不送翻译。"""
    return detect_chat_channel([text]) is not None and (
        len(normalize_channel_ocr(text)) <= 6
        or normalize_channel_ocr(text) in CHAT_CHANNEL_TITLES
    )



# ── 配置 ────────────────────────────────────────────────────
def save_cfg(region, geom=None, extra=None):
    prof = display_profile()
    data = {
        "version": 2,
        "region": list(region) if region else None,
        "dpi": prof["dpi"],
        "monitor": prof["monitor"],
        "geom": geom,
    }
    if extra:
        data.update(extra)
    try:
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_cfg():
    meta = {"topmost": True, "alpha": 0.96, "font_size": 11, "scaled": False,
            "smart_mode": True}
    try:
        with open(CFG, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None, None, meta
    meta["topmost"] = bool(d.get("topmost", True))
    meta["alpha"] = float(d.get("alpha", 0.96))
    meta["font_size"] = int(d.get("font_size", 11))
    meta["smart_mode"] = bool(d.get("smart_mode", True))
    geom = d.get("geom")
    r = d.get("region")
    if not (r and len(r) == 4):
        return None, geom, meta
    region = tuple(int(v) for v in r)
    old_dpi = int(d.get("dpi") or 0)
    old_mon = d.get("monitor")
    prof = display_profile()
    if old_dpi and (old_dpi != prof["dpi"] or (
            old_mon and list(old_mon) != list(prof["monitor"]))):
        scaled = scale_region(region, old_dpi, prof["dpi"], old_mon, prof["monitor"])
        if scaled:
            region = scaled
            meta["scaled"] = True
            save_cfg(region, geom, {
                "topmost": meta["topmost"],
                "alpha": meta["alpha"],
                "font_size": meta["font_size"],
                "smart_mode": meta.get("smart_mode", True),
            })
    return region, geom, meta


def pick_region(root):
    ov = tk.Toplevel(root)
    ov.attributes("-topmost", True)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    ov.geometry(f"{sw}x{sh}+0+0")
    ov.configure(bg="#0d1117")
    ov.attributes("-alpha", 0.32)
    ov.overrideredirect(True)
    cv = tk.Canvas(ov, bg="#0d1117", cursor="crosshair", highlightthickness=0)
    cv.pack(fill="both", expand=True)
    cv.create_text(sw // 2, 48, fill="#7ee787",
                   font=("Microsoft YaHei UI", 14, "bold"),
                   text="拖动框选游戏聊天区域 · Esc / 右键取消")
    sel = {"x0": 0, "y0": 0, "rect": None, "info": None}

    def down(e):
        sel.update(x0=e.x_root, y0=e.y_root)
        if sel["rect"]:
            cv.delete(sel["rect"])
        if sel["info"]:
            cv.delete(sel["info"])
        sel["rect"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#3fb950", width=2)
        sel["info"] = cv.create_text(e.x + 8, e.y - 12, fill="#f0f6fc", anchor="sw",
                                     font=("Consolas", 11), text="")

    def move(e):
        if not sel["rect"]:
            return
        x0 = sel["x0"] - cv.winfo_rootx()
        y0 = sel["y0"] - cv.winfo_rooty()
        cv.coords(sel["rect"], x0, y0, e.x, e.y)
        w, h = abs(e.x_root - sel["x0"]), abs(e.y_root - sel["y0"])
        cv.itemconfigure(sel["info"], text=f"{w} × {h}")
        cv.coords(sel["info"], min(x0, e.x) + 8, min(y0, e.y) - 8)

    def up(e):
        x0, y0 = min(sel["x0"], e.x_root), min(sel["y0"], e.y_root)
        w, h = abs(e.x_root - sel["x0"]), abs(e.y_root - sel["y0"])
        ov.destroy()
        if w > 30 and h > 15:
            root.region = (x0, y0, w, h)
            root._persist()
            root.log(f"区域已设定: {w}×{h} @ {x0},{y0} · DPI {display_profile()['dpi']}")
            if getattr(root, "smart_mode", False):
                root.set_status(
                    f"已框选 {w}×{h} · 智能等待频道标题，或点▶开始")
            else:
                root.set_status(f"已框选 {w}×{h} · 请点▶开始")
        else:
            root.log("框选过小, 已取消")

    def cancel(_e=None):
        ov.destroy()
        root.log("已取消框选")

    cv.bind("<ButtonPress-1>", down)
    cv.bind("<B1-Motion>", move)
    cv.bind("<ButtonRelease-1>", up)
    cv.bind("<Button-3>", cancel)
    ov.bind("<Escape>", cancel)
    ov.focus_force()


# ── 词表编辑 UI ─────────────────────────────────────────────
class GlossaryDialog(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("游戏词表")
        self.attributes("-topmost", True)
        self.geometry("460x420")
        self.configure(bg=BG2)
        tk.Label(self, text="用户词表（覆盖内置同名项）· 保存在 glossary.json",
                 bg=BG2, fg=FG, font=("Microsoft YaHei UI", 9)).pack(
                     anchor="w", padx=10, pady=(8, 4))
        frm = tk.Frame(self, bg=BG2)
        frm.pack(fill="both", expand=True, padx=10, pady=4)
        self.listbox = tk.Listbox(frm, font=("Consolas", 10), bg=BG, fg=FG,
                                  selectbackground="#3a465c", relief="flat")
        sb = tk.Scrollbar(frm, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_sel)

        edit = tk.Frame(self, bg=BG2)
        edit.pack(fill="x", padx=10, pady=4)
        tk.Label(edit, text="原文", bg=BG2, fg=FG_DIM).grid(row=0, column=0, sticky="w")
        tk.Label(edit, text="中文", bg=BG2, fg=FG_DIM).grid(row=0, column=1, sticky="w")
        self.ent_term = tk.Entry(edit, bg=BG, fg=FG, insertbackground=FG, relief="flat")
        self.ent_zh = tk.Entry(edit, bg=BG, fg=FG, insertbackground=FG, relief="flat")
        self.ent_term.grid(row=1, column=0, sticky="ew", padx=(0, 6), ipady=3)
        self.ent_zh.grid(row=1, column=1, sticky="ew", ipady=3)
        edit.columnconfigure(0, weight=1)
        edit.columnconfigure(1, weight=1)

        btns = tk.Frame(self, bg=BG2)
        btns.pack(fill="x", padx=10, pady=(4, 10))
        for text, cmd, color in (
            ("添加/更新", self.on_add, "#238636"),
            ("删除选中", self.on_del, "#da3633"),
            ("刷新", self.refresh, "#30363d"),
            ("关闭", self.destroy, "#30363d"),
        ):
            tk.Button(btns, text=text, command=cmd, relief="flat", bd=0,
                      bg=color, fg="#fff", font=("Microsoft YaHei UI", 9),
                      padx=10, pady=4, cursor="hand2").pack(side="left", padx=3)
        self.refresh()

    def refresh(self):
        self.listbox.delete(0, "end")
        for k, v in sorted(USER_GLOSSARY.items()):
            src = "用户"
            self.listbox.insert("end", f"{k}  →  {v}  [{src}]")
        # 也列出内置供参考（不可在此删）
        for k, v in sorted(BUILTIN_JARGON.items()):
            if k not in USER_GLOSSARY:
                self.listbox.insert("end", f"{k}  →  {v}  [内置]")

    def _on_sel(self, _e=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        line = self.listbox.get(sel[0])
        if "→" not in line:
            return
        left, right = line.split("→", 1)
        term = left.strip()
        zh = right.split("[")[0].strip()
        self.ent_term.delete(0, "end")
        self.ent_term.insert(0, term)
        self.ent_zh.delete(0, "end")
        self.ent_zh.insert(0, zh)

    def on_add(self):
        try:
            key = set_user_term(self.ent_term.get(), self.ent_zh.get())
            self.app.log(f"词表已更新: {key} → {USER_GLOSSARY[key]}", "ok")
            self.refresh()
        except Exception as e:
            messagebox.showerror("词表", str(e), parent=self)

    def on_del(self):
        term = self.ent_term.get().strip()
        if not term:
            return
        if delete_user_term(term):
            self.app.log(f"已删除用户词: {term}", "sys")
            self.refresh()
        else:
            messagebox.showinfo("词表", "只能删除用户词（内置词请用覆盖）", parent=self)


# ── UI ──────────────────────────────────────────────────────
MIN_W, MIN_H = 320, 200
BORDER = 8
BG, BG2 = "#1a1f2b", "#252b3a"
FG, FG_DIM = "#d6dde8", "#8b95a8"
ACCENT, ERR, ZH = "#3fb950", "#f85149", "#3fb950"


class RestoreChip(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#238636")
        self.geometry("52x52+16+16")
        lbl = tk.Label(self, text="译", bg="#238636", fg="#fff",
                       font=("Microsoft YaHei UI", 16, "bold"), cursor="hand2")
        lbl.pack(fill="both", expand=True)
        for w in (self, lbl):
            w.bind("<Button-1>", lambda e: app.restore_from_chip())
            w.bind("<Button-3>", lambda e: app.on_close())
        self.withdraw()

    def show_chip(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"52x52+{sw - 72}+{sh - 120}")
        self.deiconify()
        self.lift()

    def hide_chip(self):
        self.withdraw()


class App(tk.Tk):
    POLL_MS = 1000

    def __init__(self):
        super().__init__()
        load_user_glossary()
        self.region, geom, meta = load_cfg()
        self.topmost_on = meta.get("topmost", True)
        self.alpha = float(meta.get("alpha", 0.96))
        self.font_size = int(meta.get("font_size", 11))
        self.overrideredirect(True)
        self.attributes("-topmost", self.topmost_on)
        try:
            self.attributes("-alpha", max(0.55, min(1.0, self.alpha)))
        except Exception:
            pass
        self.geometry(geom or "640x480+40+80")
        self.minsize(MIN_W, MIN_H)
        self.configure(bg=BG)
        self.running = False
        self.seen = OrderedDict()
        self.pending = {}          # norm_key -> (hits, last_raw, last_ts)
        self.SEEN_MAX = 160
        self.CONFIRM_HITS = 2      # 连续两帧确认再翻译，降 OCR 抖动
        self.stop_flag = threading.Event()
        self._worker_wake = threading.Event()
        self._worker_thread = None
        self._session_id = 0
        self._smart_after_id = None
        self._smart_busy = False
        self._smart_results = queue.SimpleQueue()
        self._drag = self._rz = None
        self._last_geom = ""
        self._closing = False
        self._ok_count = 0
        self._fail_count = 0
        self._fail_keys = set()
        self._reported_ocr_ru_error = ""
        self.smart_mode = bool(meta.get("smart_mode", True))
        self._manual_hold = False   # 手动停止后，等面板关掉再允许智能开启
        self._auto_running = False  # 仅智能开启的会话才允许智能自动停
        self._channel_miss = 0
        self._last_channel = None
        self._idle_hint_n = 0
        self.CHANNEL_MISS_LIMIT = 3  # 约 2–3 秒无标题 → 自动停
        self.SMART_POLL_MS = 900

        self._build_ui()
        self._install_resize_borders()
        self.chip = RestoreChip(self)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Map>", self._on_map)

        prof = display_profile()
        self.log(f"目标: 简体中文 · 源语种 {', '.join(SRC_LANGS)}")
        self.log(f"显示 DPI {prof['dpi']} · 用户词 {len(USER_GLOSSARY)} · 合并词 {len(JARGON)}")
        self.log("智能模式: " + ("开（见频道标题自动开停；手动停止仍有效）" if self.smart_mode else "关"))
        if meta.get("scaled"):
            self.log("已按新 DPI/显示器自动缩放聊天区域", "ok")
        if self.region:
            self.set_status(
                f"就绪 · 智能{'开' if self.smart_mode else '关'} · "
                f"区域 {self.region[2]}×{self.region[3]}")
        else:
            self.set_status("就绪 · 请先框选聊天区域")
            self.log("尚未框选聊天区域, 点击「框选区域」", "sys")
        if self.smart_mode and self.region:
            self._schedule_smart_tick(400)

    def _persist(self):
        save_cfg(self.region, self.geometry(), {
            "topmost": self.topmost_on,
            "alpha": self.alpha,
            "font_size": self.font_size,
            "smart_mode": self.smart_mode,
        })

    def _build_ui(self):
        # 外层留白给缩放边框
        self.shell = tk.Frame(self, bg=BG)
        self.shell.pack(fill="both", expand=True, padx=BORDER, pady=BORDER)

        head = tk.Frame(self.shell, bg=BG2, cursor="fleur", height=28)
        head.pack(fill="x", side="top")
        head.pack_propagate(False)
        title = tk.Label(head, text="Warspear 聊天翻译", bg=BG2, fg=FG,
                         font=("Microsoft YaHei UI", 9, "bold"))
        title.pack(side="left", padx=8)
        tk.Button(head, text="×", command=self.on_close, relief="flat", bd=0,
                  bg=BG2, fg=FG, activebackground=ERR, activeforeground="#fff",
                  font=("Segoe UI", 11), width=3, cursor="hand2").pack(side="right")
        tk.Button(head, text="—", command=self.on_minimize, relief="flat", bd=0,
                  bg=BG2, fg=FG, activebackground="#3a465c",
                  font=("Segoe UI", 11), width=3, cursor="hand2").pack(side="right")
        tk.Button(head, text="↘", command=self.hide_to_chip, relief="flat", bd=0,
                  bg=BG2, fg=FG, activebackground="#3a465c",
                  font=("Segoe UI", 10), width=3, cursor="hand2").pack(side="right")
        for w in (head, title):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        bar = tk.Frame(self.shell, bg=BG2)
        bar.pack(fill="x", side="top")
        self.btn_toggle = tk.Button(
            bar, text="▶ 开始", command=self.on_toggle, relief="flat", bd=0,
            bg="#238636", fg="#fff", activebackground="#2ea043",
            font=("Microsoft YaHei UI", 9, "bold"), padx=12, pady=3, cursor="hand2")
        self.btn_toggle.pack(side="left", padx=(8, 4), pady=4)
        self.btn_smart = tk.Button(
            bar, text="智能:开", command=self.toggle_smart, relief="flat", bd=0,
            bg="#1f6feb", fg="#fff", activebackground="#388bfd",
            font=("Microsoft YaHei UI", 9), padx=8, pady=3, cursor="hand2")
        self.btn_smart.pack(side="left", padx=3, pady=4)
        self._refresh_smart_btn()
        for text, cmd in (("框选区域", self.on_reselect),
                          ("词表", self.open_glossary),
                          ("置顶", self.toggle_topmost),
                          ("A+", self.font_bigger),
                          ("A-", self.font_smaller),
                          ("清空", self.clear_log)):
            tk.Button(bar, text=text, command=cmd, relief="flat", bd=0,
                      bg="#30363d", fg=FG if text != "清空" else FG_DIM,
                      activebackground="#484f58",
                      font=("Microsoft YaHei UI", 9), padx=8, pady=3,
                      cursor="hand2").pack(side="left", padx=3, pady=4)

        body = tk.Frame(self.shell, bg=BG)
        body.pack(fill="both", expand=True, padx=4, pady=(2, 0))
        self.text = tk.Text(
            body, wrap="word", font=("Microsoft YaHei UI", self.font_size),
            bg=BG, fg=FG, insertbackground=FG, relief="flat",
            highlightthickness=0, padx=4, pady=4,
            selectbackground="#3a465c", selectforeground="#ffffff")
        sb = tk.Scrollbar(body, command=self.text.yview, bg=BG2, troughcolor=BG,
                          relief="flat", bd=0, highlightthickness=0,
                          activebackground="#3a465c", elementborderwidth=0, width=10)
        self.text.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self._apply_tags()

        self.status = tk.StringVar(value="就绪")
        foot = tk.Frame(self.shell, bg=BG2, height=22)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        tk.Label(foot, textvariable=self.status, anchor="w", bg=BG2, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 8), padx=8).pack(
                     side="left", fill="x", expand=True)
        # 明显的右下角拉伸把手
        grip = tk.Label(foot, text="◢", bg="#3a465c", fg=FG, cursor="size_nw_se",
                        width=3, font=("Segoe UI", 9))
        grip.pack(side="right", fill="y")
        grip.bind("<ButtonPress-1>", lambda e: self._rz_start(e, "se"))
        grip.bind("<B1-Motion>", self._rz_move)
        self.bind("<Configure>", self._save_geom)

    def _install_resize_borders(self):
        """四边 + 四角透明热区，任意拖拽缩放。"""
        cursors = {
            "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
            "e": "sb_h_double_arrow", "w": "sb_h_double_arrow",
            "ne": "top_right_corner", "nw": "top_left_corner",
            "se": "bottom_right_corner", "sw": "bottom_left_corner",
        }
        # 用 place 覆盖在根窗口边缘
        self._edges = {}
        for edge, cur in cursors.items():
            fr = tk.Frame(self, bg=BG, cursor=cur)
            self._edges[edge] = fr
            fr.bind("<ButtonPress-1>", lambda e, ed=edge: self._rz_start(e, ed))
            fr.bind("<B1-Motion>", self._rz_move)
        self.bind("<Configure>", self._layout_edges, add="+")
        self.after(50, self._layout_edges)

    def _layout_edges(self, _e=None):
        if self._closing:
            return
        try:
            w, h = self.winfo_width(), self.winfo_height()
        except Exception:
            return
        b = BORDER
        places = {
            "n": (0, 0, w, b),
            "s": (0, h - b, w, b),
            "w": (0, 0, b, h),
            "e": (w - b, 0, b, h),
            "nw": (0, 0, b, b),
            "ne": (w - b, 0, b, b),
            "sw": (0, h - b, b, b),
            "se": (w - b, h - b, b * 2, b * 2),
        }
        for edge, (x, y, bw, bh) in places.items():
            self._edges[edge].place(x=x, y=y, width=max(1, bw), height=max(1, bh))
            self._edges[edge].lift()

    def _apply_tags(self):
        fs = self.font_size
        self.text.configure(font=("Microsoft YaHei UI", fs))
        self.text.tag_configure("zh", foreground=ZH, font=("Microsoft YaHei UI", fs))
        self.text.tag_configure("sys", foreground=FG_DIM,
                                font=("Microsoft YaHei UI", max(8, fs - 1)))
        self.text.tag_configure("err", foreground=ERR,
                                font=("Microsoft YaHei UI", max(8, fs - 1)))
        self.text.tag_configure("ok", foreground=ACCENT,
                                font=("Microsoft YaHei UI", max(8, fs - 1)))

    def font_bigger(self):
        self.font_size = min(22, self.font_size + 1)
        self._apply_tags()
        self._persist()

    def font_smaller(self):
        self.font_size = max(8, self.font_size - 1)
        self._apply_tags()
        self._persist()

    def toggle_topmost(self):
        self.topmost_on = not self.topmost_on
        self.attributes("-topmost", self.topmost_on)
        self.log("置顶: " + ("开" if self.topmost_on else "关"), "sys")
        self._persist()

    def open_glossary(self):
        GlossaryDialog(self)

    def _drag_start(self, e):
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _rz_start(self, e, edge="se"):
        self._rz = (e.x_root, e.y_root, self.winfo_width(), self.winfo_height(),
                    self.winfo_x(), self.winfo_y(), edge)

    def _rz_move(self, e):
        if not self._rz:
            return
        x0, y0, w0, h0, wx, wy, edge = self._rz
        dx, dy = e.x_root - x0, e.y_root - y0
        left, top, width, height = wx, wy, w0, h0
        if "e" in edge:
            width = max(MIN_W, w0 + dx)
        if "s" in edge:
            height = max(MIN_H, h0 + dy)
        if "w" in edge:
            width = max(MIN_W, w0 - dx)
            left = wx + (w0 - width)
        if "n" in edge:
            height = max(MIN_H, h0 - dy)
            top = wy + (h0 - height)
        self.geometry(f"{width}x{height}+{left}+{top}")
        # 大窗自动略增字号可读性
        ideal = max(8, min(18, 9 + (width - 400) // 120))
        if abs(ideal - self.font_size) >= 2 and not getattr(self, "_font_locked", False):
            # 不强制改用户手动字号：仅在默认附近时跟随
            pass

    def _save_geom(self, _e=None):
        if self._closing:
            return
        g = self.geometry()
        if g != self._last_geom:
            self._last_geom = g
            self._persist()

    def _on_map(self, _e=None):
        if self.state() == "normal" and not self.overrideredirect():
            self.overrideredirect(True)
            self.attributes("-topmost", self.topmost_on)

    def on_minimize(self):
        self.overrideredirect(False)
        self.update_idletasks()
        self.iconify()

    def hide_to_chip(self):
        self.withdraw()
        self.chip.show_chip()
        self.set_status("已隐藏 · 点击右下角「译」恢复 · 右键退出")

    def restore_from_chip(self):
        self.chip.hide_chip()
        self.deiconify()
        self.overrideredirect(True)
        self.attributes("-topmost", self.topmost_on)
        self.lift()

    def on_close(self):
        self._closing = True
        self.running = False
        self.stop_flag.set()
        self._worker_wake.set()
        self._cancel_smart_tick()
        try:
            self.chip.destroy()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def log(self, msg, tag="sys"):
        self.text.configure(state="normal")
        self.text.insert("end", msg + "\n", tag)
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear_log(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def set_status(self, s):
        self.status.set(s)

    def on_reselect(self):
        if self.running:
            self.on_toggle(False, auto=False)
        if not self.winfo_viewable():
            self.restore_from_chip()
        self.deiconify()
        self.lift()
        pick_region(self)
        self._manual_hold = False
        self._auto_running = False
        self._channel_miss = 0
        self.pending.clear()
        if self.smart_mode:
            self._schedule_smart_tick(500)

    def _refresh_smart_btn(self):
        if not hasattr(self, "btn_smart"):
            return
        if self.smart_mode:
            self.btn_smart.configure(text="智能:开", bg="#1f6feb")
        else:
            self.btn_smart.configure(text="智能:关", bg="#30363d")

    def toggle_smart(self):
        self.smart_mode = not self.smart_mode
        self._refresh_smart_btn()
        self._persist()
        self.log("智能模式: " + ("开" if self.smart_mode else "关"), "ok" if self.smart_mode else "sys")
        if self.smart_mode and self.region:
            self._schedule_smart_tick(200)
        else:
            self._cancel_smart_tick()

    def on_toggle(self, force=None, *, auto=False, channel=None):
        """force=True/False 强制开停；auto=True 表示智能触发。"""
        want = (not self.running) if force is None else bool(force)
        if want:
            if not self.region:
                if not auto:
                    self.log("请先框选聊天区域", "err")
                    self.set_status("错误 · 未设定区域")
                return
            if self.running:
                return
            if auto and self._manual_hold:
                return  # 手动停过，等面板关掉再自动开
            self.running = True
            self._session_id += 1
            self._manual_hold = False
            self._auto_running = bool(auto)
            self._idle_hint_n = 0
            self.stop_flag.clear()
            self.deiconify()
            self.lift()
            self.btn_toggle.configure(text="■ 停止", bg="#da3633",
                                      activebackground="#f85149")
            if auto and channel:
                self._last_channel = channel
                self.set_status(f"智能：已检测到{channel} · 翻译中")
                self.log(f"--- 智能开启 · {channel} ---", "ok")
            else:
                self.set_status("翻译中…（手动）")
                self.log("--- 翻译已开启（手动，智能不会因无标题而停） ---", "ok")
            # 一个常驻工作线程，停止时休眠；快速开停不会复活旧线程并重复 OCR。
            if self._worker_thread is None:
                self._worker_thread = threading.Thread(target=self.worker, daemon=True)
                self._worker_thread.start()
            self._worker_wake.set()
            if self.smart_mode:
                self._schedule_smart_tick(self.SMART_POLL_MS)
        else:
            was = self.running
            self.running = False
            self._session_id += 1
            self._auto_running = False
            self._worker_wake.clear()
            self.stop_flag.set()
            self.btn_toggle.configure(text="▶ 开始", bg="#238636",
                                      activebackground="#2ea043")
            region_s = f" · 区域 {self.region[2]}×{self.region[3]}" if self.region else ""
            if auto:
                self._manual_hold = False
                self.set_status(f"智能：聊天已关闭 · 已停止{region_s}")
                if was:
                    self.log("--- 智能停止 · 未再检测到频道标题 ---", "sys")
            else:
                # 手动停止：若当时频道仍可能开着，进入 hold
                self._manual_hold = True
                self.set_status(
                    f"已停止{region_s} · 成功 {self._ok_count} / 失败 {self._fail_count}"
                    + (" · 智能暂缓自动开" if self.smart_mode else ""))
                self.log("--- 翻译已关闭 ---", "sys")

    def _cancel_smart_tick(self):
        if self._smart_after_id is not None:
            self.after_cancel(self._smart_after_id)
            self._smart_after_id = None

    def _schedule_smart_tick(self, delay):
        self._cancel_smart_tick()
        if not self._closing and self.smart_mode and self.region:
            self._smart_after_id = self.after(delay, self._smart_tick)

    def _smart_tick(self):
        """单一定时器收取后台标题检测结果；Tk 主线程不等待模型或 OCR 锁。"""
        self._smart_after_id = None
        if self._closing or not self.smart_mode or not self.region:
            return

        if self._smart_busy:
            try:
                region, channel, error = self._smart_results.get_nowait()
            except queue.Empty:
                self._schedule_smart_tick(100)
                return
            self._smart_busy = False
            if region == tuple(self.region):
                if error and not getattr(self, "_smart_err_once", False):
                    self._smart_err_once = True
                    self.log(f"智能检测 OCR 异常: {error}", "err")
                self._apply_smart_channel(channel)
                self._schedule_smart_tick(self.SMART_POLL_MS)
                return

        region = tuple(self.region)
        results = self._smart_results
        def scan_title():
            try:
                texts = ocr_all_texts(chat_title_region(region))
                results.put((region, detect_chat_channel(texts), None))
            except Exception as e:
                results.put((region, None, str(e)))
        self._smart_busy = True
        threading.Thread(target=scan_title, daemon=True).start()
        self._schedule_smart_tick(100)

    def _apply_smart_channel(self, channel):
        """见频道标题→开；仅智能开启的会话在丢标题后自动停。"""

        if channel:
            self._channel_miss = 0
            self._last_channel = channel
            if self._manual_hold:
                # 面板仍在，继续 hold；等消失后再清
                if not self.running:
                    self.set_status(
                        f"智能暂缓 · 已见{channel}，等面板关闭后再自动开（或点▶开始）")
            elif not self.running:
                self.on_toggle(True, auto=True, channel=channel)
            elif self.running:
                self.set_status(
                    f"智能：已检测到{channel} · 翻译中 · 成功 {self._ok_count}")
        else:
            self._channel_miss += 1
            if self._channel_miss >= self.CHANNEL_MISS_LIMIT:
                if self._manual_hold:
                    self._manual_hold = False  # 面板已关，下次可自动开
                # 关键：只有智能开启的会话才因丢标题而停；手动开始不受影响
                if self.running and self._auto_running:
                    self.on_toggle(False, auto=True)
                self._channel_miss = self.CHANNEL_MISS_LIMIT  # 封顶
            if not self.running and not self._manual_hold:
                self.set_status(
                    "智能：等待频道标题（世界/交易/私密/队伍/区域/公会）· 也可点▶开始")


    def _confirm_line(self, line: str):
        """两帧确认 + 去重。返回应翻译的原文或 None。"""
        key = norm_line(line)
        if not key and EMOTE_TOKEN not in line:
            return None
        # 已展示过
        if key and key in self.seen:
            self.seen.move_to_end(key)
            return None
        for sk in list(self.seen.keys())[-40:]:
            if key and similar_key(key, sk):
                return None
        now = time.time()
        hits, last_raw, _ = self.pending.get(key or line, (0, line, now))
        # 同一内容再出现
        if last_raw == line or (key and norm_line(last_raw) == key):
            hits += 1
        else:
            hits = 1
        self.pending[key or line] = (hits, line, now)
        # 清理过期 pending
        for k, (_, _, ts) in list(self.pending.items()):
            if now - ts > 12:
                del self.pending[k]
        if hits < self.CONFIRM_HITS:
            return None
        # 确认
        if key:
            self.seen[key] = now
            while len(self.seen) > self.SEEN_MAX:
                self.seen.popitem(last=False)
        self.pending.pop(key or line, None)
        return line

    def worker(self):
        empty_streak = 0
        last_frame_id = None
        last_session_id = None
        while not self._closing:
            self._worker_wake.wait()
            if self._closing:
                return
            if not self.running:
                continue
            session_id = self._session_id
            if session_id != last_session_id:
                last_session_id = session_id
                last_frame_id = None
                empty_streak = 0
            try:
                now = time.time()
                for key, (_, _, ts) in list(self.pending.items()):
                    if now - ts > 12:
                        self.pending.pop(key, None)
                # 第一次识别的候选强制再识别一次，随后静止画面跳过推理。
                lines, raw_n, frame_id = _ocr_chat_frame(self.region, force=bool(self.pending))
                if self.stop_flag.is_set() or session_id != self._session_id:
                    continue
                if _ocr_ru_error and _ocr_ru_error != getattr(self, "_reported_ocr_ru_error", ""):
                    self._reported_ocr_ru_error = _ocr_ru_error
                    self.after(0, lambda err=_ocr_ru_error: self.log(
                        f"俄语识别暂不可用: {err}；其它识别继续，可修复模型后重启", "err"))
                fresh_frame = frame_id != last_frame_id
                last_frame_id = frame_id
                got_any = False
                for line in lines if fresh_frame else []:
                    if self.stop_flag.is_set() or session_id != self._session_id:
                        break
                    if is_channel_title_line(line):
                        continue
                    confirmed = self._confirm_line(line)
                    if not confirmed:
                        continue
                    got_any = True
                    empty_streak = 0
                    zh = translate(confirmed)
                    if self._closing:
                        return
                    if self.stop_flag.is_set() or session_id != self._session_id:
                        # 已确认但尚未显示的行不能留在 seen；重启后仍需重新处理。
                        self.seen.pop(norm_line(confirmed), None)
                        break
                    if zh and not zh.startswith("[翻译失败"):
                        self._ok_count += 1
                        self.after(0, lambda z=zh: self.show_zh(z))
                        tag = "智能" if self._auto_running else "手动"
                        self.after(0, lambda t=tag: self.set_status(
                            f"翻译中 · {t} · 成功 {self._ok_count}"))
                    elif zh.startswith("[翻译失败"):
                        nk = norm_line(confirmed)
                        if nk not in self._fail_keys:
                            self._fail_keys.add(nk)
                            self._fail_count += 1
                            self.after(0, lambda z=zh: self.log(z, "err"))
                        self.after(0, lambda: self.set_status(
                            f"错误 · 翻译失败 ×{self._fail_count}（自动换线重试中）"))
                if not got_any:
                    empty_streak += 1
                    if empty_streak >= 3 and empty_streak % 3 == 0:
                        if lines:
                            hint = "等待新聊天"
                        elif raw_n == 0:
                            hint = "未检测到文字 · 检查框选是否盖住聊天"
                        else:
                            hint = "未检测到聊天行（需「名字: 内容」）· 可调不透明或重框选"
                        self.after(0, lambda h=hint: self.set_status(
                            f"翻译中 · {h} · 成功 {self._ok_count}"))
            except Exception as e:
                if self._closing:
                    return
                self.after(0, lambda err=e: self.log(f"OCR 错误: {err}", "err"))
                self.after(0, lambda: self.set_status("错误 · OCR"))
                self.stop_flag.wait(2)
            self.stop_flag.wait(self.POLL_MS / 1000)

    def show_zh(self, zh):
        self.text.configure(state="normal")
        self.text.insert("end", zh + "\n", "zh")
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > 500:
            self.text.delete("1.0", f"{lines - 350}.0")
        self.text.see("end")
        self.text.configure(state="disabled")


# ── 自检 ────────────────────────────────────────────────────
def selftest():
    bad = 0

    def check(ok, msg):
        nonlocal bad
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {msg}")

    load_user_glossary()

    for t, want in [("WTS chaos scroll 500k", True), ("Onko myydän 500k", True),
                    ("Bán giá rẻ đây", True), ("Продаю щит", True),
                    ("안녕하세요 거래", True), ("ดรอปมั้ง", True),
                    ("Yojo: ของคราฟ", True), ("帮我看下", False),
                    ("こんにちは", False), ("12345", False), ("", False)]:
        check(need_translate(t) == want,
              f"gate({t[:22]!r}) = {need_translate(t)} want {want}")

    for w, want in [("WTS", "出售"), ("wts", "出售"), ("wts!", "出售"),
                    ("lfp3", "组满3人"), ("pm", "私聊"), ("signs", "不朽符号"),
                    ("dmg 3", "三级武器强化材料"), ("gz", "恭喜"),
                    ("hello", None), ("cw", None), ("and", None), ("or", None),
                    ("线上聊天", None)]:
        check(glossary_hit(w) == want,
              f"glossary({w!r}) = {glossary_hit(w)!r} want {want!r}")

    # 内置词表自检不受用户 glossary.json 影响
    _saved_user = dict(USER_GLOSSARY)
    USER_GLOSSARY.clear()
    rebuild_jargon()
    try:
        for src, want in [("tpt pm adv tank", "TPT 私聊 分支 坦克"),
                          ("buy signs and dmg 3 pm",
                           "求购 不朽符号 and 三级武器强化材料 私聊"),
                          ("kultaa kiitos", "kultaa kiitos"),
                          ("Onko myydän", "Onko myydän"),
                          ("Продаю щит", "Продаю щит"),
                          ("sell chest 43k", "出售 宝箱 43k"),
                          ("EZ HERO TECH LAST SLOT", "EZ 英雄装备 附魔 最后位置")]:
            got = apply_terms(src)
            check(got == want, f"terms({src[:30]!r}) -> {got!r}")
    finally:
        USER_GLOSSARY.clear()
        USER_GLOSSARY.update(_saved_user)
        rebuild_jargon()

    for t, want in [("hello", "en"), ("안녕하세요", "ko"),
                    ("Продаю", "ru"), ("Bán giá", "vi"),
                    ("ดรอปมั้ง", "th"), ("ของคราฟ", "th")]:
        check(detect_from_lang(t) == want,
              f"lang({t!r}) = {detect_from_lang(t)} want {want}")

    r = scale_region((100, 200, 400, 300), 96, 144)
    check(r == (150, 300, 600, 450), f"dpi_scale {r}")

    check(norm_line("Hello,  World!") == norm_line("hello world"), "norm_line")

    # 聊天线形 / 空间过滤
    check(is_chat_shaped("Qzz: sell chest 43k"), "chat_shape_ok")
    check(is_chat_shaped("Takberdaya：apaan"), "chat_shape_cn_colon")
    check(not is_chat_shaped("Teemo"), "chat_shape_name_only")
    check(not is_chat_shaped("角斗士皮革工人"), "chat_shape_npc")
    check(not is_chat_shaped("Aum:"), "chat_shape_empty_body")
    check(is_chat_shaped("Yojo: ดรอปมั้ง"), "chat_shape_thai")
    check(is_chat_shaped("Ninesixzo: ของคราฟ 【表情】"), "chat_shape_thai_emote")
    check(is_chat_shaped("민수: hello"), "chat_shape_hangul_name")
    check(is_chat_shaped("Иван: привет"), "chat_shape_cyrillic_name")
    check(is_chat_shaped("9tails: wts chest"), "chat_shape_digit_name")
    check(is_chat_shaped("สมชาย: ขาย"), "chat_shape_thai_name")

    # 智能频道标题
    check(detect_chat_channel(["世界聊天"]) == "世界聊天", "ch_world")
    check(detect_chat_channel(["交易聊天"]) == "交易聊天", "ch_trade")
    check(detect_chat_channel(["私密聊天"]) == "私密聊天", "ch_priv")
    check(detect_chat_channel(["队伍聊天"]) == "队伍聊天", "ch_party")
    check(detect_chat_channel(["区域聊天"]) == "区域聊天", "ch_area")
    check(detect_chat_channel(["公会聊天"]) == "公会聊天", "ch_guild")
    check(detect_chat_channel(["信息"]) is None, "ch_info_ignore")
    check(detect_chat_channel(["信息: 系统公告"]) is None, "ch_info_line")
    check(detect_chat_channel(["世 界 聊 天"]) == "世界聊天", "ch_spaces")
    check(detect_chat_channel(["世界明天"]) == "世界聊天", "ch_ocr_noise")
    check(is_channel_title_line("世界聊天"), "ch_title_line")
    check(not is_channel_title_line("Qzz: sell chest"), "ch_not_title")

    rows = [
        (10, "Ann: hi", 0, 50, 1), (30, "Bob: yo", 0, 50, 1), (50, "Cat: zz", 0, 50, 1),
        (200, "FloatingName", 80, 120, 1),  # 离群飘字
    ]
    got = filter_dense_chat_rows(rows)
    check(got == ["Ann: hi", "Bob: yo", "Cat: zz"], f"spatial_filter {got!r}")


    # 表情归一
    e1 = normalize_emotes("hello 😀 world")
    check(EMOTE_TOKEN in e1 and "hello" in e1 and "world" in e1,
          f"emote_unicode {e1!r}")
    e2 = normalize_emotes("WTS ◆ signs")
    check(EMOTE_TOKEN in e2 and "WTS" in e2, f"emote_noise {e2!r}")
    e3 = normalize_emotes("★★")
    check(is_emote_only(normalize_emotes("★★")) or e3 == EMOTE_TOKEN,
          f"emote_only {e3!r}")
    # 纯表情翻译
    check(translate("😀😀") == EMOTE_TOKEN or translate("■") == EMOTE_TOKEN,
          f"emote_translate {translate('■')!r}")

    # 用户词表合并 + 整词边界
    global GLOSSARY_FILE
    import tempfile
    fd, tmpg = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    old_g = GLOSSARY_FILE
    GLOSSARY_FILE = tmpg
    try:
        USER_GLOSSARY.clear()
        set_user_term("wdv", "测试词")
        check(JARGON.get("wdv") == "测试词", f"user_merge {JARGON.get('wdv')!r}")
        got = apply_terms("tpt wdv tank")
        check(got == "TPT 测试词 坦克", f"user_terms {got!r}")
        # 不切碎
        check(apply_terms("awdvx") == "awdvx", f"boundary {apply_terms('awdvx')!r}")
        delete_user_term("wdv")
        check("wdv" not in USER_GLOSSARY, "user_delete")
    finally:
        GLOSSARY_FILE = old_g
        load_user_glossary()
        try:
            os.remove(tmpg)
        except Exception:
            pass

    merged = _merge_line_boxes([(10, 0, "buy", 1), (12, 40, "signs", 1), (40, 0, "pm", 1)])
    check(len(merged) == 2 and "buy" in merged[0][1], f"merge_lines {merged}")

    for t in ("WTS chaos scroll 500k", "안녕하세요 거래 가능하신가요",
              "Onko myydän 500k kultaa, kiitos", "Bán giá rẻ đây, 500k nhé",
              "Estou vendendo 500k, obrigado", "Продаю щит за 200k",
              "Yojo: ดรอปมั้ง", "Ninesixzo: ได้แน่ครับ",
              "Ninesixzo: ของคราฟ 【表情】"):
        out = translate(t)
        check(bool(out) and not out.startswith("[翻译失败"),
              f"API({t[:28]!r}) -> {out!r}")

    _saved_user2 = dict(USER_GLOSSARY)
    USER_GLOSSARY.clear()
    rebuild_jargon()
    CACHE.clear(); CACHE_NORM.clear()
    try:
        out = translate("Windrider: tpt pm adv tank")
        check(out.startswith("Windrider:") and "TPT" in out and "私聊" in out,
              f"speaker -> {out!r}")
    finally:
        USER_GLOSSARY.clear()
        USER_GLOSSARY.update(_saved_user2)
        rebuild_jargon()
    out = translate("WTS chaos scroll 500k")
    check(out != "", f"cache -> {out!r}")

    # 配置往返
    global CFG
    old_cfg = CFG
    fd2, tmpc = tempfile.mkstemp(suffix=".json")
    os.close(fd2)
    CFG = tmpc
    try:
        save_cfg((10, 20, 30, 40), "100x100+1+1", {"topmost": False, "font_size": 12})
        region, geom, meta = load_cfg()
        check(region == (10, 20, 30, 40) and meta["font_size"] == 12,
              f"cfg_roundtrip {region} {meta}")
    finally:
        CFG = old_cfg
        try:
            os.remove(tmpc)
        except Exception:
            pass

    print("失败数:", bad)
    return 1 if bad else 0


def _fix_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _fix_stdio()
        sys.exit(selftest())
    enable_dpi_awareness()
    load_user_glossary()
    App().mainloop()
