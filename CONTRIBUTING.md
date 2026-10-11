# 开发与反馈

使用 Windows、Python 3.12 64 位。运行 `run.bat` 安装依赖；随后可关闭插件窗口再执行检查。

```bat
.venv\Scripts\python.exe -X utf8 -m unittest discover -v
run.bat --selftest
```

离线回归覆盖截图识别、系统消息过滤、俄语/泰语选择、画面缓存、两帧确认和 UI 线程状态。联网自检调用 Bing，请避免频繁重复运行。

测试使用临时配置文件，不应覆盖使用者的 `config.json` 或 `glossary.json`。模型文件已包含在仓库；不要提交 `.venv`、本机窗口配置、访问令牌、日志或调试输出。

提交问题时请说明版本、Windows/Python 版本、聊天语言、框选范围及具体错误。可附遮去私人信息的局部截图；不要提供游戏密码或 GitHub 令牌。

本项目保持独立屏幕 OCR，不加入游戏内存读取、封包捕获、本地大语言模型、付费 API Key 或全局热键。修改语言选择规则时，同时验证英文、俄语、泰语和中文公告。
