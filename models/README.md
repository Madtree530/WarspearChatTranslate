# OCR 模型

PP-OCRv5 多语言移动端识别模型，由 RapidAI/RapidOCR 分发；原始权重与字典未修改。许可说明见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 文件与校验

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `cyrillic_PP-OCRv5_rec_mobile.onnx` | 8074092 | `90f761b4bfcce0c8c561c0cb5c887b0971d3ec01c32164bdf7374a35b0982711` |
| `ppocrv5_cyrillic_dict.txt` | 2781 | `db40aa52ceb112055be80c694afdf655d5d2c4f7873704524cc16a447ca913ba` |
| `th_PP-OCRv5_rec_mobile.onnx` | 7915294 | `de541dd83161c241ff426f7ecfd602a0ba77d686cf3ab9a6c255ea82fd08006e` |
| `ppocrv5_th_dict.txt` | 1767 | `57f5406f94bb6688fb7077f7be65f08bbd71cecf48c01ea26c522cb5c4836b7a` |

## 官方下载来源

- [cyrillic_PP-OCRv5_rec_mobile.onnx](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/cyrillic_PP-OCRv5_rec_mobile.onnx)
- [ppocrv5_cyrillic_dict.txt](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv5/rec/cyrillic_PP-OCRv5_rec_mobile/ppocrv5_cyrillic_dict.txt)
- [th_PP-OCRv5_rec_mobile.onnx](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/th_PP-OCRv5_rec_mobile.onnx)
- [ppocrv5_th_dict.txt](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/paddle/PP-OCRv5/rec/th_PP-OCRv5_rec_mobile/ppocrv5_th_dict.txt)

中英检测与识别模型随 `rapidocr-onnxruntime==1.4.4` 依赖安装；这些俄语/泰语模型复用主引擎检测框，仅执行文本识别。
