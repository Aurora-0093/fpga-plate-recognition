#!/usr/bin/env python3
"""对比 conv_engine 仿真输出与软件参考结果。"""
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "sim"

exp = np.fromfile(OUT / "expected.bin", dtype=np.int32)

words = []
for line in (OUT / "out.hex").read_text().split():
    w = int(line, 16)
    if w >= 2**31:
        w -= 2**32
    words.append(w)
got = np.array(words, dtype=np.int32)

n = min(len(exp), len(got))
exp = exp[:n]
got = got[:n]

bad = np.nonzero(exp != got)[0]
print(f"比较 {n} 个元素，不一致 {len(bad)} 个")
if len(bad):
    for i in bad[:10]:
        print(f"  idx {i}: 期望 {exp[i]}  实际 {got[i]}")
else:
    print("✅ 硬件与软件结果完全一致（bit-exact）")
