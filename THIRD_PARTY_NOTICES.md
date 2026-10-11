# 第三方组件说明

本项目自己的代码和初始术语表使用 [MIT 许可](LICENSE)。第三方组件和模型保留各自的许可，MIT 不替代它们。

## OCR 模型

俄语和泰语识别模型及字典由 [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) 分发，使用 PaddleOCR 的 PP-OCRv5 多语言识别模型。本项目直接使用原始 ONNX 权重和字典，没有修改权重。

- RapidOCR：Copyright (c) 2021 RapidOCR Authors，Apache License 2.0；完整许可见 [licenses/RapidOCR-Apache-2.0.txt](licenses/RapidOCR-Apache-2.0.txt)。
- PaddleOCR：Copyright (c) 2020 PaddlePaddle Authors，Apache License 2.0；完整许可见 [licenses/PaddleOCR-Apache-2.0.txt](licenses/PaddleOCR-Apache-2.0.txt)。
- 模型文件、下载地址和 SHA256 见 [models/README.md](models/README.md)。
- 中英检测/识别模型随 `rapidocr-onnxruntime` 依赖提供。

## Python 依赖

依赖由 pip 从 PyPI 安装，未将整个 Python 环境打包分发。项目使用 mss、Pillow、RapidOCR、NumPy、OpenCV、ONNX Runtime、pyclipper 和 Shapely；各包的版权和许可以所安装发行包中的许可文件为准。

## 名称与服务

Warspear Online 是游戏及其权利人的名称；本项目是玩家制作的独立辅助工具，与游戏官方没有隶属或合作关系。Bing 翻译服务由 Microsoft 提供，服务本身不属于本项目的 MIT 许可范围。

测试截图用于验证 OCR 行为，不作为本项目原创游戏美术发布；其中游戏画面和玩家消息不属于本项目的 MIT 授权范围。
