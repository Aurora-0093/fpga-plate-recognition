# Python 代码

模型训练、量化导出、上位机三部分。

环境：Python 3.9+，依赖 `torch / onnx / opencv-python / numpy / pyserial / pywin32`。

---

## train —— 训练

| 文件 | 说明 |
|---|---|
| `model.py` | LPRNet 模型定义。输入 1×32×128 灰度，输出 7 个时间步 × 41 类 |
| `dataset.py` | 数据集加载，读图 → 转灰度 → resize 128×32 → 归一化 |
| `1_augment.py` | 数据增强：旋转、透视、亮度对比度扰动、模糊、加噪声 |
| `2_split.py` | 划分 train / val / test |
| `3_train.py` | 训练主脚本 |
| `4_test.py` | 评估整牌准确率和单字符准确率 |
| `5_export.py` | 导出 ONNX |

按顺序跑：

```bat
python 1_augment.py
python 2_split.py
python 3_train.py
python 4_test.py
python 5_export.py
```

模型结构：

```
输入 1×32×128
  conv1  1 → 32,   32×128
  pool   32 → 16×64
  conv2  32 → 64,  16×64
  pool   64 → 8×32
  conv3  64 → 128, 8×32
  pool   128 → 4×32
  conv4  128 → 256, 4×32
  fc     16384 → 287  (7 时间步 × 41 类)
```

41 个类别 = 36 个字母数字 + 沪、陕、粤、贵、赣。

---

## convert —— 量化与权重导出

| 文件 | 说明 |
|---|---|
| `export_sw_weights.py` | 从 ONNX 提取每层的 int8 权重、int32 偏置、三个量化系数，输出 `.bin`（5,092,636 字节） |
| `gen_weights_c.py` | 把 `.bin` 转成 `weights_lprnet41.c`，可直接编译进 ELF |
| `sw_ref.py` | Python 参考实现（纯整数推理），和 C 引擎逐位对拍 |
| `test_quant_accuracy.py` | 量化前后精度对比 |

### 数据流

```
LPRNet (PyTorch)
      │ 5_export.py
      ▼
  lprnet.onnx
      │ export_sw_weights.py   ← 量化：权重 int8、激活 uint8、累加 int32
      ▼
lprnet_sw.bin  (5,092,636 字节)
      │ gen_weights_c.py
      ▼
weights_lprnet41.c  →  编译进 Zynq 的 ELF
      │
      └──► sw_ref.py 逐位对拍 ◄── lprnet_sw.c（C 引擎）
```

### 量化方案

- 权重：int8 对称量化，每层一个 scale
- 激活：uint8（0~255）
- 累加：int32
- 输出：`clamp(acc × (w_scale × a_scale / out_scale), 0, 255)`

量化后的模型和浮点模型整牌准确率一致，这是 `test_quant_accuracy.py` 验证的。

---

## tools —— 上位机

### web_show.py —— 网页实时显示

```bat
python web_show.py
```

浏览器打开 **http://127.0.0.1:8000**（注意端口是 **8000**，不是 8080）。

顶部的开关：

| 变量 | 说明 |
|---|---|
| `MODE` | 1=无硬件模拟，2=接 20K 原图 PC 推理，3=接 Zynq 单牌，4=接 Zynq 双牌 |
| `SERIAL_PORT` | 留空自动找 CH340 |
| `SERIAL_BAUD` | 921600 |
| `TTS_ENABLE` | 是否语音播报车牌（Windows SAPI，中文女声） |
| `TTS_MODE` | 1=同车牌只念一次，2=每次都念，3=N 秒内不重复 |
| `FAKE_INFER` | 网页上显示的耗时：True=随机数，False=板子返回值 |

界面功能：大屏车牌 + 128×32 灰度图 + 距离/颜色/车型/推理耗时、语音播报、历史记录（一帧一行）、清空历史按钮。

### 其他工具

| 文件 | 用途 |
|---|---|
| `pc_send_frame.py` | PC 发图给 Zynq，统计耗时并校验软件参考与板子结果的一致性 |
| `uart_aa55_capture.py` | AA55 帧协议解析库，被 `web_show.py` 引用 |
| `test_zynq_accuracy.py` | 批量准确率测试，从文件名解析真值逐张比对 |
| `dump_serial.py` | 串口原始数据抓包诊断，统计字节数、AA55 帧头数、文本行 |
| `test_20k_uart.py` | 20K 串口诊断，自动遍历 115200 / 230400 / 921600 / 460800 猜波特率 |

---

## 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `PermissionError(13, '拒绝访问')` | 串口被占用 | 关掉 SSCOM 或其他 Python 进程 |
| 网页打不开 | 端口记错 | 是 `8000` 不是 `8080` |
| 语音不响 | 系统没中文语音包 | 设置 → 时间和语言 → 语音 → 添加「中文(简体)」 |
| `SyntaxError: invalid non-printable character U+FEFF` | 文件存成了 UTF-8 BOM | 用无 BOM 的 UTF-8 重新保存 |
