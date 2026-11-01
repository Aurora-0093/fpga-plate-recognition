#!/usr/bin/env python3
"""在电脑上评估量化模型的准确度：浮点 ONNX vs int8 TFLite，并给出量化损失。

用法（在 plate_project 目录下）：
    D:\\Miniconda\\envs\\d2l\\python.exe test_quant_accuracy.py
    D:\\Miniconda\\envs\\d2l\\python.exe test_quant_accuracy.py --split split/test --limit 500
    D:\\Miniconda\\envs\\d2l\\python.exe test_quant_accuracy.py --captures   # 额外测 FPGA 抓图

说明：
  - 测试集划分 + labels.txt 提供真值；
  - int8 TFLite 是用 raw/ 校准过的全整数量化模型，最接近 138K 上 GoAI 的 int8；
  - 输出：整体准确率、各车牌准确率、错误样例（保存到 quant_errors/）。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ沪陕粤贵赣"
IMG_W, IMG_H = 128, 32
ROOT = Path(__file__).resolve().parent

# 最近一批 FPGA 抓图的真值（test_picture\gray_XXXX_128x32.jpg）
CAPTURE_LABELS = {
    "gray_0001_128x32.jpg": "粤C54321", "gray_0002_128x32.jpg": "粤C54321", "gray_0003_128x32.jpg": "粤C54321",
    "gray_0004_128x32.jpg": "陕E86420", "gray_0005_128x32.jpg": "陕E86420", "gray_0006_128x32.jpg": "陕E86420",
    "gray_0007_128x32.jpg": "沪B67890", "gray_0008_128x32.jpg": "沪B67890", "gray_0009_128x32.jpg": "沪B67890",
}


def read_gray(path: Path):
    import cv2
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return cv2.resize(img, (IMG_W, IMG_H))


def load_split(split_dir: Path, labels_file: Path, limit: int | None):
    labels = {}
    with open(labels_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                n, l = line.split()
                labels[n] = l
    items = []
    for n, l in labels.items():
        p = split_dir / n
        if p.is_file():
            items.append((p, l))
    if limit:
        items = items[:limit]
    return items


def decode_logits(out):
    out = np.asarray(out).reshape(7, len(CHARS))
    return "".join(CHARS[int(i)] for i in out.argmax(axis=1))


def make_onnx_runner(path: Path):
    import onnxruntime as ort
    sess = ort.InferenceSession(str(path))
    name = sess.get_inputs()[0].name

    def run(gray):
        x = (gray.astype(np.float32) / 255.0)[None, None, :, :]
        out = sess.run(None, {name: x})[0]
        return decode_logits(np.asarray(out).squeeze(0))

    return run


def make_tflite_runner(path: Path):
    import tensorflow as tf
    interp = tf.lite.Interpreter(model_path=str(path))
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out_det = interp.get_output_details()[0]
    in_shape = inp["shape"]           # NHWC 或 NCHW
    dtype = inp["dtype"]
    quant = inp.get("quantization", (0.0, 0))
    scale, zp = (quant if isinstance(quant, tuple) else (0.0, 0))
    if scale == 0:
        scale = 1.0

    def run(gray):
        h = gray.astype(np.float32)
        if in_shape[1] == IMG_H:      # NHWC (1,32,128,1)
            data = h[None, :, :, None]
        else:                          # NCHW (1,1,32,128)
            data = h[None, None, :, :]
        data = data / 255.0                  # 与 onnx2tflite.py 的校准一致：输入按 0~1 归一化
        if dtype == np.uint8:
            data = np.clip(np.round(data / scale) + zp, 0, 255).astype(np.uint8)
        elif dtype == np.int8:
            data = np.clip(np.round(data / scale) + zp, -128, 127).astype(np.int8)
        else:
            data = data.astype(np.float32)   # 浮点输入（0~1）
        interp.set_tensor(inp["index"], data)
        interp.invoke()
        out = interp.get_tensor(out_det["index"])[0]
        if out_det["dtype"] == np.int8:
            o_scale, o_zp = out_det["quantization"]
            out = (out.astype(np.float32) - o_zp) * o_scale
        return decode_logits(out)

    return run


def evaluate(name, runner, items, err_dir: Path | None = None):
    per_plate_total = defaultdict(int)
    per_plate_ok = defaultdict(int)
    total = ok = 0
    errors = []
    for path, truth in items:
        gray = read_gray(path)
        if gray is None:
            continue
        pred = runner(gray)
        total += 1
        per_plate_total[truth] += 1
        if pred == truth:
            ok += 1
            per_plate_ok[truth] += 1
        else:
            errors.append((path, truth, pred))
    print(f"[{name}] 准确率: {ok}/{total} = {100.0*ok/max(total,1):.2f}%")
    for plate in sorted(per_plate_total):
        print(f"    {plate}: {per_plate_ok[plate]}/{per_plate_total[plate]}")
    if errors and err_dir:
        err_dir.mkdir(parents=True, exist_ok=True)
        import cv2
        for path, truth, pred in errors[:20]:
            gray = read_gray(path)
            cv2.imencode(".png", gray)[1].tofile(str(err_dir / f"{truth}_pred{pred}_{path.name}"))
        print(f"    错误样例已保存 {min(len(errors),20)} 张 -> {err_dir}")
    return ok, total


def main() -> int:
    parser = argparse.ArgumentParser(description="PC 上评估量化模型准确度")
    parser.add_argument("--split", type=Path, default=Path("split/test"))
    parser.add_argument("--labels", type=Path, default=Path("labels.txt"))
    parser.add_argument("--onnx", type=Path, default=Path("lprnet.onnx"))
    parser.add_argument("--tflite-int8", type=Path, default=Path("lprnet_int8.tflite"))
    parser.add_argument("--limit", type=int, default=None, help="只测前 N 张（快速试跑）")
    parser.add_argument("--captures", action="store_true", help="额外评估 FPGA 抓图（test_picture）")
    parser.add_argument("--holdout", action="store_true", help="评估 holdout/ 独立真机验证集（文件名 hu_/shan_/yue_ 前缀即标签）")
    args = parser.parse_args()

    items = load_split(args.split, args.labels, args.limit)
    if not items:
        print("测试集为空，请检查 split/labels.txt", file=sys.stderr)
        return 2
    print(f"测试样本: {len(items)} 张（{args.split}）\n")

    runners = []
    if args.onnx.is_file():
        runners.append(("float ONNX", make_onnx_runner(args.onnx)))
    if args.tflite_int8.is_file():
        runners.append(("int8 TFLite", make_tflite_runner(args.tflite_int8)))

    for name, run in runners:
        evaluate(name, run, items, err_dir=ROOT / "quant_errors")

    if args.captures:
        cap_dir = ROOT / "test_picture"
        cap_items = [(cap_dir / n, l) for n, l in CAPTURE_LABELS.items()
                     if (cap_dir / n).is_file()]
        if cap_items:
            print()
            for name, run in runners:
                evaluate(f"{name} @FPGA抓图", run, cap_items)

    if args.holdout:
        hold_dir = ROOT / "holdout"
        prefix_map = {"hu_": "沪B67890", "shan_": "陕E86420", "yue_": "粤C54321"}
        hold_items = []
        if hold_dir.is_dir():
            for p in sorted(hold_dir.iterdir()):
                if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                    continue
                for pre, plate in prefix_map.items():
                    if p.name.startswith(pre):
                        hold_items.append((p, plate))
                        break
        if hold_items:
            print()
            for name, run in runners:
                evaluate(f"{name} @holdout(独立真机图)", run, hold_items)
        else:
            print("\nholdout 目录为空或没有 hu_/shan_/yue_ 命名的图片，跳过")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
