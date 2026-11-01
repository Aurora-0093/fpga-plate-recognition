#!/usr/bin/env python3
"""把量化后的模型同步到 Zynq 工程：
   1) 复制 sw_model/lprnet_sw.{bin,c,h} -> zynq_project/app/
   2) 把 lprnet_sw.bin 转成 C 数组 weights.c

用法（训练/导出后跑一次即可）：
    D:\\Miniconda\\envs\\d2l\\python.exe gen_weights_c.py
"""
import shutil
from pathlib import Path

SW_DIR = Path(r"D:\fpga_plate_recognition\plate_project\sw_model")
APP_DIR = Path(r"D:\fpga_plate_recognition\zynq_project\app")

# 1) 同步模型文件到 Zynq 工程
copied = []
for name in ("lprnet_sw.bin", "lprnet_sw.c", "lprnet_sw.h"):
    src = SW_DIR / name
    if src.exists():
        shutil.copy2(src, APP_DIR / name)
        copied.append(name)

bin_data = (APP_DIR / "lprnet_sw.bin").read_bytes()

# 2) 生成 weights.c
lines = [
    "/* auto-generated LPRNet weights (int8 weights + int32 bias) for Zynq bare-metal app */",
    "const unsigned char lprnet_weights[] = {",
]
PER = 24
for i in range(0, len(bin_data), PER):
    chunk = bin_data[i:i + PER]
    lines.append("    " + ",".join(f"0x{b:02x}" for b in chunk) + ",")
lines.append("};")
lines.append(f"const unsigned int lprnet_weights_len = {len(bin_data)};")
lines.append("")

(APP_DIR / "weights.c").write_text("\n".join(lines), encoding="ascii")

print("已同步:", ", ".join(copied) if copied else "(无)")
print("已生成:", APP_DIR / "weights.c")
print("权重字节数:", len(bin_data))
print("提示: 之后在 Vitis 里重新 Build lprnet_app 即可")
