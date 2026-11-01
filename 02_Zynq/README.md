# Zynq-7020 卷积加速

正点原子 领航者 ZYNQ7020（XC7Z020-2CLG400I），双核 Cortex-A9，1 GB DDR3。
工具 Vivado / Vitis 2026.1。

把 LPRNet 里最耗时的 conv2 / conv3 / conv4 卸载到 PL，其余（conv1、池化、全连接、bias、requant）留在 ARM。

## 目录

```
pl_accel/
├── rtl/                    卷积加速器 RTL
│   ├── conv_engine.v       计算核心，16 路 int8 并行
│   ├── conv_accel.v        控制层
│   ├── dpram.v             早期版本的双口 RAM（留档）
│   ├── tb_conv.v           引擎仿真台
│   ├── tb_accel.v          控制层仿真台
│   ├── tb_conv_gen.py      生成随机测试向量
│   └── tb_conv_check.py    比对 RTL 输出与期望值
├── lprnet_accel.c / .h     ARM 驱动
├── lprnet_sw.c / .h        软件参考实现（用于比对验证）
├── main_accel.c            主程序
├── create_bd.tcl           Block Design 脚本
├── bd_accel_export.tcl     已建好 BD 的导出脚本
├── build_bit.tcl           构建比特流
├── export_xsa.tcl          导出 XSA
├── lprnet_zynq.xdc         引脚约束
└── UserConfig.cmake        编译选项
weights/
└── weights_lprnet41.c      模型权重（int8 权重 + int32 偏置）
```

## 架构

```
ARM (Cortex-A9) ──AXI4──► axi_bram_ctrl ──► blk_mem_gen（真双口 BRAM，256 KB）
                                                    ▲ 端口 B
                                                    │
                                             conv_accel（控制层）
                                                    │
                                             conv_engine（卷积核心）
```

### conv_engine

| 参数 | 默认值 | 说明 |
|---|---|---|
| `OC_PAR` | 16 | 并行输出通道数 |
| `OW_CHUNK` | 8 | 每次并行处理的输出像素数 |

支持的卷积配置：3×3 核、pad = 1、stride = 1（LPRNet 所有卷积层都是这个配置）。

内部结构：

- 状态机：`S_IDLE → S_CLEAR → S_ADDR/S_WAIT → S_WDATA → S_ADDR/S_WAIT → S_PDATA → S_ADDR → S_FIN`
- 累加器阵列 `acc[0 : OC_PAR × OW_CHUNK - 1]`，每个 32 bit
- BRAM 接口：字地址、1 拍同步读延迟

### conv_accel

用 BRAM 前 9 个字当控制寄存器，省掉手写 AXI-Lite 从机：

| BRAM 地址 | 内容 |
|---|---|
| `0x00` | CTRL/STATUS：bit0 = start，bit1 = busy，bit2 = done |
| `0x04` | C_IN |
| `0x08` | C_OUT |
| `0x0C` | H_IN |
| `0x10` | W_IN |
| `0x14` | 权重区字节偏移 |
| `0x18` | 输入区字节偏移 |
| `0x1C` | 输出区字节偏移 |
| `0x20` | CYCLES（引擎写回的周期数） |

## 设计要点

### FPGA 只做卷积累加

bias 加法、requant（乘量化系数并 clamp）、池化、全连接全部留在 ARM。

这样只要 int32 累加结果一致，整条链路就和软件实现逐位一致，可以用「两个实现跑同一张图、对比 7 个输出字符」来验证 —— 这是 `main_accel.c` 里 `DBG:` 那一行的来源。

### 权重打包格式

为了让一次 32 位读取就能拿到 4 个通道的同一个权重，权重按 16 通道一块重排：

```
wblk[ ((ocb*c_in + ic)*9 + kh*3 + kw)*16 + lane ]
       ↑ 第几个 16 通道块   ↑ 第几个抽头      ↑ 块内通道号
```

### BRAM 内存布局（256 KB）

| 区域 | 字节偏移 | 容量 |
|---|---|---|
| 控制字（9 个） | `0x000000` | 64 B |
| 权重区（当前块） | `0x000100` | 147,456 B |
| 输入区 | `0x025000` | 32 KB |
| 输出区（int32） | `0x02E000` | 64 KB |

### 分块策略

受 BRAM 容量限制，每层卷积按输出通道自动分块：

| 层 | 输出通道 | 每通道像素 | 分块数 | 每块通道 |
|---|---|---|---|---|
| conv2 | 64 | 1024 | 4 | 16 |
| conv3 | 128 | 256 | 2 | 64 |
| conv4 | 256 | 128 | 2 | 128 |

## 仿真验证

```bat
cd rtl
python tb_conv_gen.py      :: 生成随机测试向量
:: 用 Vivado xsim 跑 tb_conv.v / tb_accel.v
python tb_conv_check.py    :: 比对结果
```

| 用例 | 结果 |
|---|---|
| 简单用例（单位权重） | 256 / 256 一致 |
| 随机用例（C_IN=4, C_OUT=32, H=8, W=16） | **4096 / 4096 一致（bit-exact）** |
| 控制层（含 BRAM 模型） | 4096 / 4096 一致 |

仿真阶段发现并修复的 RTL 缺陷：

- `lane` 计数器位宽不足，导致像素循环无法退出
- `kh/kw` 变化时没有重新读取权重
- BRAM 有 1 拍同步读延迟，状态机少等一拍，读到的是上一个地址的数据
- uint8 输入被符号扩展成 int8（正确做法是零扩展）

## Block Design

```
Zynq PS7（DDR3 参数按正点原子官方 XSA）
  ├── FCLK_CLK0 = 100 MHz
  ├── UART0 → MIO14/15（PC 通信，921600）
  └── M_AXI_GP0 → AXI Interconnect（1 主 3 从）
                    ├── AXI UART Lite（收 20K 图像，230400，rx = T19）
                    ├── AXI GPIO（2 位 LED，H15 / L15）
                    └── axi_bram_ctrl + blk_mem_gen(256 KB) + conv_accel
```

> ⚠️ PS7 的 DDR3 参数必须按开发板真实型号（MT41K256M16）配。用默认的 MT41J128M8 会导致 DDR 初始化失败，现象是比特流下载成功、LED 正常，但串口一个字都没有。

## 编译

### 1. 建 Block Design

```bat
vivado -mode batch -source create_bd.tcl
```

### 2. 生成比特流

```bat
vivado -mode batch -source build_bit.tcl
```

### 3. 应用工程

Vitis 里新建应用，把 `pl_accel/*.c`、`pl_accel/*.h` 和 `weights/weights_lprnet41.c` 加进去。

编译选项：

```cmake
set(USER_COMPILE_OPTIMIZATION_LEVEL -O3)
set(USER_COMPILE_OPTIMIZATION_OTHER_FLAGS -funroll-loops)
set(USER_COMPILE_OTHER_FLAGS -mfpu=neon)
```

> Vitis 会缓存 CMake 配置，改完选项必须 **Clean → Build** 才生效。

## 输出格式（Zynq → PC，921600 波特率）

```
TIME:xxx ms                   推理耗时
DBG: SW=赣DF0002 ACCEL=赣DF0002 MATCH     软件参考与 FPGA 逐类比对
PLATE:赣DF0002,0.95           车牌号, 置信度
INFO:255,0                    颜色, 距离
IMG:4096 + 4096 字节          灰度图回显
```

## 当前状态

RTL 与驱动已完成，仿真逐位验证通过。

综合目前在本机 Vivado 2026.1 上不稳定：

- 全 Block Design：崩在 Timing Optimization 阶段
- 单模块 OOC 综合：崩在 Final Netlist Cleanup（`Tcl_AsyncDelete`）

所以还没有上板数据。后续计划：

1. 换 Vivado 2020.2 / 2022.2（7 系列在那两版上更稳定）重新综合
2. 加速器改用 AXI4-Stream + DMA，权重放 DDR，突破 BRAM 容量限制
3. 加宽 BRAM 读端口、提高并行路数与时钟，进一步提升吞吐

## 第三方代码

`lprnet_sw.c` 是 LPRNet 前向传播的纯整数参考实现，用于和 FPGA 结果对拍。
