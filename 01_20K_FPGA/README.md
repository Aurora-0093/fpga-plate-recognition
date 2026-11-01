# 20K FPGA 工程（Gowin GW2A-18C）

Tang Primer 20K 上的车牌定位工程。摄像头采集 → 定位 → 裁成 128×32 灰度 → 串口送出。

## 文件说明

### 核心模块

| 文件 | 说明 |
|---|---|
| `src/image_process.v` | 整个工程的算法主体。形态学滤波、外接矩形定位、128×32 降采样、UART 发送、LCD 画框、状态 LED |
| `src/top.v` | 顶层。时钟 PLL、摄像头 I2C 初始化、DDR3 帧缓存读写仲裁、LCD 时序、`image_process` 例化、UART 扇出 |

### 图像处理流水线

| 文件 | 说明 |
|---|---|
| `src/rgb2ycbcr.v` | RGB565 转 YCbCr，后面只用亮度 Y |
| `src/binarization.v` | 单阈值二值化，阈值 140 |
| `src/VIP_Bit_Erosion_Detector.v` | 3×3 腐蚀，去掉噪点 |
| `src/Sobel_Edge_Detector.v` | Sobel 边缘检测，阈值 128 |
| `src/VIP_Bit_Dilation_Detector.v` | 3×3 膨胀，把边缘连成整块 |
| `src/matrix_generate_3x3_8bit.v` | 8 位数据 3×3 滑窗 |
| `src/matrix_generate_3x3_1bit.v` | 1 位数据 3×3 滑窗 |
| `src/line_shift_ram_8bit.v` | 三行行缓存 |
| `src/gowin_sdpb_1024x8.v` | Gowin 双口 RAM，行缓存用 |

### 定位辅助

| 文件 | 说明 |
|---|---|
| `src/VIP_horizon_projection.v` | 水平投影，统计每行黑点数 |
| `src/VIP_vertical_projection.v` | 垂直投影，统计每列黑点数 |
| `src/gowin_sdpb_1024x10.v` | 上面两个投影模块用的 RAM |

### 摄像头与显示

| 文件 | 说明 |
|---|---|
| `src/cmos_8_16bit.v` | 摄像头 8 位数据并成 16 位 RGB565 |
| `src/i2c_config.v` | 上电配置 OV5640 寄存器 |
| `src/i2c_master_top.v` / `i2c_master_bit_ctrl.v` / `i2c_master_byte_ctrl.v` / `i2c_master_defines.v` | I2C 主机控制器 |
| `src/lut_ov5640_rgb565_480_272.v` | OV5640 寄存器表，输出 480×272 |
| `src/syn_gen.v` | LCD 时序生成 |

### DDR3 与时钟（Gowin IP，不要手改）

`DDR3MI.v`、`Video_Frame_Buffer_Top.v`、`video_fifo.v`、`sys_pll.v`、`cmos_pll.v`、`mem_pll.v`，以及各自的 `.ipc` 配置文件。

### 约束

| 文件 | 说明 |
|---|---|
| `src/top.cst` | 引脚约束。`uart_tx` → M11，`uart_tx_gpio` → R8，两个脚同一路信号 |
| `src/lcd.sdc` | LCD 时钟时序约束 |
| `src/top.rao` / `src/fpga_projectnumber.rao` | 布局约束 |

## 编译

```bat
"D:\Gowin_V1.9.12.04_x64_win\Gowin\Gowin_V1.9.12.04_x64\IDE\bin\gw_sh.exe" < build.tcl
```

输出 `impl\pnr\fpga_projectnumber.fs`（约 7.26 MB）。

## 关键参数

| 参数 | 值 | 位置 |
|---|---|---|
| 系统时钟 | 27 MHz | `sys_pll.v` |
| UART 波特率 | 230400 | `image_process.v` 的 `BAUD_DIV = 117` |
| 每帧字节数 | 4103 | `FRAME_BYTES` |
| 摄像头分辨率 | 480 × 272 | `lut_ov5640_rgb565_480_272.v` |
| 车牌裁剪 | 128 × 32 | `image_process.v` |
| 二值化阈值 | 140 | `image_process.v` |
| Sobel 阈值 | 128 | `image_process.v` |

## 注意

- `DDR3MI.v` 等 Gowin IP 文件是工具生成的，重新生成会覆盖，不要手改
- 改 UART 波特率时，20K 和 Zynq 的 AXI UART Lite 两边要一起改，否则收不到数据
