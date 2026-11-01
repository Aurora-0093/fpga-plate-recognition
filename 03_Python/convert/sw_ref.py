#!/usr/bin/env python3
"""软件推理的参考实现（与将要在 AE350 上跑的 C 代码逐位等价）。

读取 export_sw_weights.py 生成的 sw_model/lprnet_sw.bin + lprnet_sw.json：
    conv: int32 累加（int8 权重 × uint8 激活）→ + int32 bias → 乘 mult → clamp 0..255
    pool: 窗口取最大（uint8，不改变 scale）
    fc:   int32 累加 + bias → 每个时间步取 argmax

用法（在 plate_project 目录下）：
    python sw_ref.py                      # 跑 split/test 前 200 张
    python sw_ref.py --n 500              # 指定数量
    python sw_ref.py --dir test_picture   # 跑指定目录（按文件名猜标签）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ沪陕粤贵赣"
ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "sw_model"

class SwLPRNet:
    def __init__(self, model_dir: Path = MODEL_DIR):
        meta = json.loads((model_dir / "lprnet_sw.json").read_text(encoding="utf-8"))
        self.layers = meta["layers"]
        self.bin = np.fromfile(model_dir / "lprnet_sw.bin", dtype=np.uint8)
        self.classes = meta["classes"]
        self.timesteps = meta["timesteps"]

    def _weights(self, layer):
        off, ln = layer["w_offset"], layer["w_len"]
        return self.bin[off:off + ln].view(np.int8).copy()

    def _bias(self, layer):
        off, ln = layer["b_offset"], layer["b_len"]
        return self.bin[off:off + 4 * ln].view(np.int32).copy()

# 各层
    def conv(self, a: np.ndarray, layer) -> np.ndarray:
        """a: (cin,H,W) uint8 → (cout,H,W) uint8"""
        cin, cout = layer["in_ch"], layer["out_ch"]
        kh, kw, pad = layer["kh"], layer["kw"], layer["pad"]
        w = self._weights(layer).reshape(cout, cin, kh, kw).astype(np.int32)
        b = self._bias(layer)
        mult = np.float32(layer["w_scale"]) * np.float32(layer["a_scale"]) / np.float32(layer["out_scale"])
        _, h, wd = a.shape
        ap = np.zeros((cin, h + 2 * pad, wd + 2 * pad), np.int32)
        ap[:, pad:pad + h, pad:pad + wd] = a
        acc = np.zeros((cout, h, wd), np.int32)
        for y in range(kh):
            for x in range(kw):
                patch = ap[:, y:y + h, x:x + wd]                 # (cin,h,wd)
                acc += np.tensordot(w[:, :, y, x], patch, axes=([1], [0]))
        acc += b[:, None, None]
        out = np.rint(acc.astype(np.float32) * np.float32(mult))
        return np.clip(out, 0, 255).astype(np.uint8)

    def pool(self, a: np.ndarray, layer) -> np.ndarray:
        kh, kw = layer["kh"], layer["kw"]
        sh, sw = layer["stride_h"], layer["stride_w"]
        c, h, w = a.shape
        oh, ow = h // sh, w // sw
        out = np.full((c, oh, ow), 0, np.uint8)
        for y in range(kh):
            for x in range(kw):
                sub = a[:, y:y + (oh - 1) * sh + 1:sh, x:x + (ow - 1) * sw + 1:sw]
                out = np.maximum(out, sub)
        return out

    def fc(self, a: np.ndarray, layer) -> np.ndarray:
        w = self._weights(layer).reshape(layer["out_features"], layer["in_features"]).astype(np.int32)
        b = self._bias(layer)
        x = a.reshape(-1).astype(np.int32)
        acc = w.dot(x) + b
        return acc

# 整图
    def infer(self, img32x128: np.ndarray):
        """img32x128: uint8 (32,128) → (字符串, 7 个类别下标)"""
        a = img32x128[None, :, :].astype(np.uint8)      # (1,32,128)
        logits = None
        for layer in self.layers:
            t = layer["type"]
            if t == "conv":
                a = self.conv(a, layer)
            elif t == "pool":
                a = self.pool(a, layer)
            else:
                logits = self.fc(a, layer)
        scores = logits.reshape(self.timesteps, self.classes)
        cls = scores.argmax(axis=1)
        text = "".join(CHARS[int(c)] for c in cls)
        return text, cls, scores

def load_gray(path: Path) -> np.ndarray:
    import cv2
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    return cv2.resize(img, (128, 32))

def main() -> int:
    ap = argparse.ArgumentParser(description="软件推理参考实现评测")
    ap.add_argument("--dir", type=Path, default=ROOT / "split" / "test")
    ap.add_argument("--labels", type=Path, default=ROOT / "labels.txt")
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()

    net = SwLPRNet()
    labels = {}
    if args.labels.is_file():
        for line in args.labels.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                labels[parts[0]] = parts[1]

    files = sorted(p for p in args.dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))[:args.n]
    ok = total = 0
    shown = 0
    for p in files:
        truth = labels.get(p.name)
        if truth is None:
            continue
        img = load_gray(p)
        text, cls, _ = net.infer(img)
        total += 1
        if text == truth:
            ok += 1
        elif shown < 8:
            shown += 1
            print(f"  错例 {p.name}: 真值={truth} 预测={text}")
    print(f"软件推理（整数）准确率: {ok}/{total} = {100.0*ok/max(total,1):.2f}%")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
