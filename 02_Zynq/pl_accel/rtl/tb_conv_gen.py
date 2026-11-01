#!/usr/bin/env python3
"""随机大数据测试向量：C_IN=4, C_OUT=32, H=8, W=16（与 tb_conv.v 一致）。"""
from pathlib import Path

import numpy as np

C_IN, C_OUT, H, W = 4, 32, 8, 16
OC_PAR = 16
OUT = Path(__file__).resolve().parent / "sim"
OUT.mkdir(exist_ok=True)

rng = np.random.default_rng(2026)
wt = rng.integers(-127, 128, size=(C_OUT, C_IN, 3, 3), dtype=np.int16).astype(np.int8)
inp = rng.integers(0, 256, size=(C_IN, H, W), dtype=np.int32).astype(np.uint8)

pad = np.zeros((C_IN, H + 2, W + 2), dtype=np.int32)
pad[:, 1:-1, 1:-1] = inp.astype(np.int32)
ref = np.zeros((C_OUT, H, W), dtype=np.int32)
for oc in range(C_OUT):
    for ic in range(C_IN):
        for kh in range(3):
            for kw in range(3):
                ref[oc] += wt[oc, ic, kh, kw].astype(np.int32) * pad[ic, kh:kh + H, kw:kw + W]
ref.tofile(OUT / "expected.bin")

wblob = bytearray()
for ocb in range(C_OUT // OC_PAR):
    for ic in range(C_IN):
        for kh in range(3):
            for kw in range(3):
                for lane in range(OC_PAR):
                    wblob.append(int(wt[ocb * OC_PAR + lane, ic, kh, kw]) & 0xFF)


def write_hex(path, data):
    words = []
    for i in range(0, len(data), 4):
        ch = data[i:i + 4] + b"\x00" * (4 - len(data[i:i + 4]))
        words.append(int.from_bytes(ch, "little"))
    path.write_text("\n".join(f"{w:08x}" for w in words) + "\n")


write_hex(OUT / "weights.hex", bytes(wblob))
write_hex(OUT / "input.hex", inp.tobytes())
print(f"C_IN={C_IN} C_OUT={C_OUT} H={H} W={W}")
print(f"权重 {len(wblob)}B / 输入 {inp.size}B / 参考输出 {ref.size} 个 int32")
