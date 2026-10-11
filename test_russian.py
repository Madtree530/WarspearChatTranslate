"""Russian screenshot and Chinese-output translation regressions."""
import io
import json
import os
import unittest
from collections import OrderedDict
from unittest.mock import patch

from PIL import Image

import wptrans as w
from test_performance import FakeOCR


class RussianModelFailureTests(unittest.TestCase):
    def test_failed_russian_model_retains_english_and_is_not_retried_each_frame(self):
        image = Image.new("RGB", (400, 300), "black")
        with patch.object(w, "_capture_region", return_value=image), \
             patch.object(w, "_get_ocr_engines", return_value=(FakeOCR(), None)), \
             patch.object(w, "_get_russian_recognizer", side_effect=RuntimeError("model unavailable")) as load, \
             patch.object(w, "_ocr_ru", None), \
             patch.object(w, "_ocr_ru_error", "", create=True):
            try:
                lines, _, _ = w._ocr_chat_frame((0, 0, 400, 300), force=True)
            except RuntimeError as error:
                self.fail(f"Russian failure aborted English OCR: {error}")
            self.assertEqual(lines, ["Ann: hello"])
            self.assertIn("model unavailable", w._ocr_ru_error)
            lines, _, _ = w._ocr_chat_frame((0, 0, 400, 300), force=True)
            self.assertEqual(lines, ["Ann: hello"])
            self.assertEqual(load.call_count, 1)


class RussianScreenshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Image.open(os.path.join(w.HERE, "tests", "fixtures", "russian_chat.png")) as source:
            image = source.convert("RGB")
        with patch.object(w, "_capture_region", return_value=image):
            cls.lines, _, _ = w._ocr_chat_frame((0, 0, *image.size), force=True)

    def test_real_russian_body_and_original_latin_speaker_are_retained(self):
        bodies = dict(w.split_speaker(line) for line in self.lines)
        for speaker, words in {
                "Fanatbarba": ("КУПЛЮ", "ТКАНЬ", "ЗАМКА"),
                "Tixomag": ("продам", "смирение", "обменяю"),
                "Kingsolo": ("куп", "кожа", "точность"),
                "Chumpion": ("знаки", "продам"),
                "Gopstop": ("ПРОДАМ", "МНОГО"),
                "Amberluck": ("Куплю", "свитки", "устоя")}.items():
            with self.subTest(speaker=speaker):
                self.assertIn(speaker, bodies)
                for word in words:
                    self.assertIn(word, bodies[speaker])
                self.assertEqual(w.detect_from_lang(bodies[speaker]), "ru")

    def test_russian_decoder_does_not_turn_system_notices_into_player_chat(self):
        self.assertEqual(len(self.lines), 18)
        self.assertFalse(any(name in " ".join(self.lines)
                             for name in ("Suneater", "Pleasemom", "Mrhram", "Mestermen")))


class RussianTranslationTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("CACHE", OrderedDict()), ("CACHE_NORM", OrderedDict()),
                            ("JARGON", dict(w.BUILTIN_JARGON)), ("_TERM_SUB", None),
                            ("MIN_INTERVAL", 0), ("LAST_CALL", 0)):
            p = patch.object(w, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_chinese_character_does_not_skip_russian_body(self):
        self.assertTrue(w.need_translate("куплю 护甲 32 pm"))
        self.assertFalse(w.need_translate("求购护甲"))
        with patch.object(w, "bing_translate", return_value="求购护甲，私聊") as api:
            self.assertEqual(w.translate("Kingsolo: куплю 护甲 32 pm"),
                             "Kingsolo: 求购护甲，私聊")
        self.assertEqual(api.call_args.args[1], "ru")

    def test_glossary_hint_does_not_short_circuit_russian_translation(self):
        with patch.object(w, "bing_translate", return_value="求购护甲，私聊") as api:
            self.assertEqual(w.translate("Pigas: куплю armor pm"),
                             "Pigas: 求购护甲，私聊")
        self.assertEqual(api.call_args.args[1], "ru")
        self.assertIn("护甲", api.call_args.args[0])

    def test_russian_speaker_with_chinese_body_does_not_translate_the_name(self):
        with patch.object(w, "bing_translate", side_effect=AssertionError("Name sent to Bing")):
            self.assertEqual(w.translate("Иван: 求购护甲"), "")

    def test_extended_cyrillic_ocr_speaker_is_removed_from_body(self):
        primary = [(10, 10, "Tixomag: npoAaM cMNpeHNe", 0.86, 10, 900)]
        russian = [(10, 10, "Тіхотад: продам смирение", 0.96, 10, 900)]
        merged = w._prefer_russian_merge(primary, russian)
        self.assertEqual(merged[0][2], "Tixomag: продам смирение")


class BingChineseOutputTests(unittest.TestCase):
    def translate_response(self, translations, text="знаки продам"):
        class Opener:
            def open(self, request, timeout):
                return io.BytesIO(json.dumps([{"translations": translations}]).encode("utf-8"))

        with patch.object(w, "_ordered_hosts", return_value=["www.bing.com"]), \
             patch.object(w, "bing_token", return_value=("ig", "iid", 1, "token", "www.bing.com")), \
             patch.object(w, "_bing_tok", [None, 0, Opener()]), \
             patch.object(w, "_preferred_host", [None]), patch.object(w, "_mark_host"):
            return w.bing_translate(text, "ru")

    def test_selects_chinese_result_instead_of_first_translation(self):
        self.assertEqual(self.translate_response([
            {"text": "знаки продам", "to": "ru"},
            {"text": "出售符号", "to": "zh-Hans"}]), "出售符号")

    def test_russian_output_is_not_reported_as_successful_chinese_translation(self):
        with self.assertRaises(RuntimeError):
            self.translate_response([{"text": "знаки продам", "to": "zh-Hans"}])

    def test_unchanged_russian_with_chinese_hint_is_rejected(self):
        for response in ("куплю 护甲 pm", "КУПЛЮ   护甲 PM!"):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                self.translate_response([{"text": response, "to": "zh-Hans"}],
                                        text="куплю 护甲 pm")


if __name__ == "__main__":
    unittest.main()
