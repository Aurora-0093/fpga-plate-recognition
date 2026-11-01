# FPGA 车牌识别系统

一个跑在 Gowin FPGA + Xilinx Zynq 上的端侧车牌识别方案。

摄像头采集的画面先在 Tang Primer 20K（Gowin GW2A-18C）上完成定位与裁剪：把 480×272 的 RGB565
图像转成 YCbCr 只留亮度，依次经过二值化、3×3 腐蚀、Sobel 边缘、3×3 膨胀这一串形态学处理，
把车牌区域滤成一整块，然后求外接矩形、归一化并下采样成 128×32 灰度图，通过 UART 送给 Zynq。
整条流水线靠行缓存逐行推进，不需要把整帧存下来再处理。

Zynq-7020 收到灰度图后运行量化后的 LPRNet——权重 int8、激活 uint8、累加 int32。
网络里最耗时的三个卷积层（conv2/conv3/conv4）卸载到 PL 端的自研卷积加速器，
bias、量化、池化、全连接这些留在 ARM 上，两边共用一份权重。
为了让软硬件结果可比，加速器只做卷积累加，其余全部用软件实现——这样只要 int32 累加一致，
整条链路就逐位一致，可以用「同一张图两边各跑一遍、比对 7 个输出字符」来验证。
识别结果连同灰度图一起回传给 PC，网页端实时显示车牌号、置信度、距离和车型。

工程分成三部分：

- `01_20K_FPGA` —— Verilog 写的定位流水线，含约束、比特流和编译脚本
- `02_Zynq` —— PL 端卷积加速器的 RTL、ARM 驱动，以及 Block Design 脚本
- `03_Python` —— 模型训练、量化导出、上位机网页与调试工具

## 目录结构

```
.
├── 01_20K_FPGA/          20K 工程（Gowin）
│   ├── src/              30 个 Verilog + 引脚 / 时序约束
│   ├── bitstream/        已编译好的比特流
│   └── build.tcl         命令行编译脚本
├── 02_Zynq/
│   ├── pl_accel/         PL 端卷积加速器（RTL + ARM 驱动）
│   └── weights/          LPRNet int8 权重
└── 03_Python/
    ├── train/            数据增强、划分、训练、测试、导出 ONNX
    ├── convert/          提取 int8 权重、生成 weights.c、逐位对拍
    └── tools/            网页显示、发图测试、串口诊断
```

---

## 一、20K FPGA

平台 Tang Primer 20K（GW2A-18C），系统时钟 27 MHz，工具 Gowin EDA V1.9.12.04。

### 处理流程

```
OV5640 摄像头 480×272 RGB565
    ↓ 转 YCbCr，只取亮度 Y
    ↓ 二值化（阈值 140）—— 车牌是白底黑字，亮的区域就是车牌
    ↓ 3×3 腐蚀 —— 去掉零星噪点
    ↓ Sobel 边缘（阈值 128）—— 把车牌边框补回来
    ↓ 3×3 膨胀 —— 把断开的边缘连成整块
    ↓ 求外接矩形，归一化成 128×32
    ↓ UART 发出 AA55 + 4096 字节灰度 + 颜色 + 距离 + 0D0A
```

整个流程在 27 MHz 下逐帧实时完成，靠行缓存流水，不需要等整帧。

### 编译

```bat
cd 01_20K_FPGA
"D:\Gowin_V1.9.12.04_x64_win\Gowin\Gowin_V1.9.12.04_x64\IDE\bin\gw_sh.exe" < build.tcl
```

输出 `impl\pnr\fpga_projectnumber.fs`。仓库里带了一份编译好的在 `bitstream/` 下，可以直接用 Gowin Programmer 烧。

### 接线

| 20K | Zynq | 说明 |
|---|---|---|
| M11 或 R8 | T19 | UART 发送，两个脚输出同一路信号 |
| GND | GND | **必须共地**，否则收不到数据 |

> M11 和 R8 是同一路信号的两个扇出，接哪个都行。

### UART 协议

| 字节 | 内容 |
|---|---|
| 2 | `AA 55` 帧头 |
| 4096 | 128×32 灰度图 |
| 1 | 车牌颜色 |
| 2 | 距离（高位在前，单位 mm） |
| 2 | `0D 0A` 帧尾 |

波特率 **230400**（`image_process.v` 里 `BAUD_DIV = 117`，27 MHz ÷ 117 = 230,769）。

---

## 二、Zynq-7020

平台正点原子 领航者 ZYNQ7020（XC7Z020-2CLG400I），双核 Cortex-A9，1 GB DDR3。工具 Vivado / Vitis 2026.1。

把 LPRNet 里最耗时的 conv2 / conv3 / conv4 卸载到 PL，其余（conv1、池化、全连接、bias、requant）留在 ARM。

### 加速器结构

```
ARM (Cortex-A9) ──AXI4──► axi_bram_ctrl ──► blk_mem_gen（真双口 BRAM，256 KB）
                                                    ▲ 端口 B
                                                    │
                                             conv_accel（控制层）
                                                    │
                                             conv_engine（卷积核心）
```

| 文件 | 说明 |
|---|---|
| `rtl/conv_engine.v` | 卷积计算核心，16 路 int8 并行乘加，3×3 / pad=1 / stride=1 |
| `rtl/conv_accel.v` | 控制层。用 BRAM 前 9 个字当控制寄存器（start / busy / done / 层参数），省掉手写 AXI-Lite 从机 |
| `rtl/tb_conv.v` | 引擎仿真台，随机权重 + 随机输入，和 Python 参考逐位比对 |
| `rtl/tb_accel.v` | 控制层仿真台，模拟 ARM 写寄存器、发 start、等 done、读结果 |
| `lprnet_accel.c` | ARM 驱动。权重重排、按输出通道分块调度、读回 int32 做 bias / requant |
| `main_accel.c` | 主程序。同一张图分别跑软件参考和 FPGA，逐类比对 |
| `create_bd.tcl` | Block Design 脚本 |
| `lprnet_zynq.xdc` | 引脚约束 |

### 设计要点

**FPGA 只做卷积累加**，bias 加法、requant、池化、全连接全留在 ARM。这样只要 int32 累加结果一致，整条链路就和软件实现逐位一致，可以用「两个实现跑同一张图、对比 7 个输出字符」来验证。

权重按 16 通道一块重排，让一次 32 位读取就能拿到 4 个通道的同一个权重：

```
wblk[ ((ocb*c_in + ic)*9 + kh*3 + kw)*16 + lane ]
```

BRAM 内存布局（256 KB）：

| 区域 | 偏移 | 容量 |
|---|---|---|
| 控制字 | 0x000000 | 64 B |
| 权重（当前块） | 0x000100 | 147,456 B |
| 输入 | 0x025000 | 32 KB |
| 输出（int32） | 0x02E000 | 64 KB |

### 仿真验证

```bat
cd 02_Zynq/pl_accel/rtl
python tb_conv_gen.py      :: 生成随机测试向量
:: 用 Vivado xsim 跑 tb_conv.v
python tb_conv_check.py    :: 比对 RTL 输出与期望值
```

| 用例 | 结果 |
|---|---|
| 简单用例（单位权重） | 256 / 256 一致 |
| 随机用例（C_IN=4, C_OUT=32, H=8, W=16） | **4096 / 4096 一致（bit-exact）** |

### Block Design

```
Zynq PS7（DDR3 参数按正点原子官方 XSA）
  ├── FCLK_CLK0 = 100 MHz
  ├── UART0 → MIO14/15（PC 通信，921600）
  └── M_AXI_GP0 → AXI Interconnect
                    ├── AXI UART Lite（收 20K 图像，230400，rx = T19）
                    ├── AXI GPIO（2 位 LED）
                    └── axi_bram_ctrl + blk_mem_gen（加速器数据通道）
```

> ⚠️ PS7 的 DDR3 参数**绝对不能改成默认值**。默认按 MT41J128M8 配，而开发板是 MT41K256M16，参数不匹配会导致 DDR 初始化失败，表现是比特流下载成功、LED 正常，但串口一个字都没有。

### 编译选项

```cmake
set(USER_COMPILE_OPTIMIZATION_LEVEL -O3)
set(USER_COMPILE_OPTIMIZATION_OTHER_FLAGS -funroll-loops)
set(USER_COMPILE_OTHER_FLAGS -mfpu=neon)
```

> Vitis 会缓存 CMake 配置，改完选项必须 **Clean → Build** 才生效。

### 输出格式（Zynq → PC，921600 波特率）

```
TIME:xxx ms                   推理耗时
DBG: SW=... ACCEL=...         软件参考与 FPGA 的逐类比对结果
PLATE:赣DF0002,0.95           车牌号, 置信度
INFO:255,0                    颜色, 距离
IMG:4096 + 4096 字节          灰度图回显
```

---

## 三、Python

环境：Python 3.9+，依赖 `torch / onnx / opencv-python / numpy / pyserial / pywin32`。

### train —— 训练

```bat
python 1_augment.py     :: 数据增强
python 2_split.py       :: 划分 train / val / test
python 3_train.py       :: 训练
python 4_test.py        :: 评估整牌准确率和单字符准确率
python 5_export.py      :: 导出 ONNX
```

模型是 LPRNet：输入 1×32×128 灰度，输出 7 个时间步 × 41 类（36 个字母数字 + 沪陕粤贵赣）。

### convert —— 量化与权重导出

```bat
python export_sw_weights.py   :: ONNX → int8 权重 + int32 偏置 + 量化系数，输出 .bin
python gen_weights_c.py       :: .bin → weights_lprnet41.c（编译进 ELF）
python sw_ref.py              :: Python 参考实现，和 C 引擎逐位对拍
```

量化方案：权重 int8 对称量化，激活 uint8，累加 int32，输出 `clamp(acc × w_scale × a_scale / out_scale, 0, 255)`。

### tools —— 上位机

```bat
python web_show.py
```

浏览器打开 **http://127.0.0.1:8000**（注意是 8000，不是 8080）。

`web_show.py` 顶部的开关：

| 变量 | 说明 |
|---|---|
| `MODE` | 1=无硬件模拟，2=接 20K 原图 PC 推理，3=接 Zynq 单牌，4=接 Zynq 双牌 |
| `SERIAL_PORT` | 留空自动找 CH340 |
| `TTS_ENABLE` | 是否语音播报车牌 |
| `FAKE_INFER` | 网页上显示的耗时：True=随机数，False=板子返回值 |

其他工具：

| 文件 | 用途 |
|---|---|
| `pc_send_frame.py` | PC 发图给 Zynq，统计耗时并校验一致性 |
| `uart_aa55_capture.py` | AA55 帧协议解析库 |
| `test_zynq_accuracy.py` | 批量准确率测试 |
| `dump_serial.py` | 串口原始数据抓包诊断 |
| `test_20k_uart.py` | 20K 串口诊断，自动猜波特率 |

---

## 已知问题

- **加速器尚未上板**：RTL 仿真验证通过（bit-exact），综合受本机 Vivado 2026.1 限制未完成
- **AXI UART Lite 波特率上限 230400**：它的波特率只能从固定列表里选
- **双牌版不是每次都能框到两块**：取决于拍摄角度和光照，检测不到时会退回画面中央的固定框

## 第三方代码

以下代码不是本项目写的，版权声明保留在文件头：

| 来源 | 文件 |
|---|---|
| OpenCores（Richard Herveille） | `i2c_master_*.v` —— WISHBONE I2C 主机 |
| 正点原子 www.openedv.com | `rgb2ycbcr.v`、`top.v` 的原始框架 |
| Gowin IP 自动生成 | `DDR3MI.v`、`Video_Frame_Buffer_Top.v`、`video_fifo.v`、`*_pll.v`、`gowin_sdpb_*.v` |
