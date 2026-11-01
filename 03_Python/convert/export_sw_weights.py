#!/usr/bin/env python3
"""把训练好的 LPRNet 导出成 AE350 软件推理用的 C 格式。

产物（sw_model/ 目录）：
    lprnet_sw.bin   所有层的 int8 权重 / int32 bias
    lprnet_sw.h     层描述（形状/步长/pad、量化参数、权重偏移）与接口声明
    lprnet_sw.json  同样的信息（便于排查）

量化方案（纯整数推理）：
    - 权重：每层对称量化 w_q = round(w / w_scale)，w_scale = max|w| / 127
    - 激活：uint8（0~255，ReLU 后非负，零点=0），每层一个 scale
    - 累加：int32；bias 预先换算为 int32（单位 = w_q * a_q）
    - 输出：out_q = clamp(round(acc * mult), 0, 255)，mult = w_scale * a_scale / out_scale
    - FC：int32 累加后直接 argmax（不需要 requant）

用法（在 plate_project 目录下）：
    D:\\Miniconda\\envs\\d2l\\python.exe export_sw_weights.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from model import LPRNet

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "sw_model"
CKPT = ROOT / "best_model.pth"
NUM_CLASSES = 41          # 36 字母数字 + 沪陕粤贵赣
IMG_H, IMG_W = 32, 128
CALIB_DIR = ROOT / "split" / "train"
CALIB_N = 300
STRIDES = [(2, 2), (2, 2), (2, 1), (2, 1)]

def load_model() -> LPRNet:
    model = LPRNet(num_classes=NUM_CLASSES)
    state = torch.load(CKPT, map_location="cpu")
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    model.load_state_dict(state)
    model.eval()
    return model

def fold_bn(conv: torch.nn.Conv2d, bn: torch.nn.BatchNorm2d):
    """把 BN 折进 conv：w' = w * gamma / sqrt(var+eps)，b' = beta - mean*scale + b*scale"""
    w = conv.weight.detach().clone()
    b = conv.bias.detach().clone() if conv.bias is not None else torch.zeros(w.size(0))
    gamma = bn.weight.detach().clone()
    beta = bn.bias.detach().clone()
    mean = bn.running_mean.detach().clone()
    var = bn.running_var.detach().clone()
    scale = gamma / torch.sqrt(var + bn.eps)
    w2 = (w * scale.view(-1, 1, 1, 1)).numpy()
    b2 = (beta - mean * scale + b * scale).numpy()
    return w2, b2

def calibrate_activations(model: LPRNet) -> list[float]:
    """统计每层 ReLU 输出在全部标定图上的最大值（用于激活量化 scale）"""
    import cv2

    maxima: list[float] = []
    hooks = []
    relus = [m for m in model.cnn.modules() if isinstance(m, torch.nn.ReLU)]

    def make_hook(idx: int):
        def hook(mod, inp, out):
            v = float(out.max())
            if idx >= len(maxima):
                maxima.append(v)
            else:
                maxima[idx] = max(maxima[idx], v)
        return hook

    for i, r in enumerate(relus):
        hooks.append(r.register_forward_hook(make_hook(i)))

    files = sorted(p for p in CALIB_DIR.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png"))[:CALIB_N]
    with torch.no_grad():
        for p in files:
            img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            img = cv2.resize(img, (IMG_W, IMG_H)).astype(np.float32) / 255.0
            model(torch.from_numpy(img)[None, None, :, :])
    for h in hooks:
        h.remove()
    if not maxima:
        raise RuntimeError("标定失败：没读到图片")
    return maxima

def quantize_weights(w: np.ndarray):
    max_abs = float(np.max(np.abs(w))) or 1e-8
    scale = max_abs / 127.0
    q = np.clip(np.round(w / scale), -127, 127).astype(np.int8)
    return q, scale

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model = load_model()

    modules = list(model.cnn.children())
    conv_bn = []
    for i, m in enumerate(modules):
        if isinstance(m, torch.nn.Conv2d):
            conv_bn.append(fold_bn(m, modules[i + 1]))

    print("标定激活范围（训练集最多 %d 张）…" % CALIB_N)
    act_max = calibrate_activations(model)
    print("  各层激活最大值:", [round(v, 4) for v in act_max])

    blobs: list[bytes] = []
    layers: list[dict] = []
    offset = 0

    # 输入激活 scale：像素 0~255 表示 0~1
    a_scales = [1.0 / 255.0]
    out_scales = [max(v, 1e-6) / 255.0 for v in act_max]

    # conv 全部 stride=1、pad=1；pool 的核/步长如下（与 model.py 一致）
    POOLS = [(2, 2, 2, 2), (2, 2, 2, 2), (2, 1, 2, 1), (2, 1, 2, 1)]

    for idx, (w, b) in enumerate(conv_bn):
        wq, w_scale = quantize_weights(w)
        out_ch, in_ch, kh, kw = wq.shape
        a_scale = a_scales[idx]
        out_scale = out_scales[idx]
        bias_q = np.round(b / (w_scale * a_scale)).astype(np.int32)
        wb, bb = int(wq.nbytes), int(bias_q.nbytes)
        blobs.append(wq.tobytes())
        blobs.append(bias_q.tobytes())
        layers.append(dict(
            type="conv", in_ch=in_ch, out_ch=out_ch, kh=kh, kw=kw,
            stride_h=1, stride_w=1, pad=1,
            w_offset=offset, w_len=int(wq.size),
            b_offset=offset + wb, b_len=int(bias_q.size),
            w_scale=w_scale, a_scale=a_scale, out_scale=out_scale))
        offset += wb + bb
        a_scales.append(out_scale)

        # 紧跟一个 pool（不改变量化 scale）
        pkh, pkw, psh, psw = POOLS[idx]
        layers.append(dict(
            type="pool", kh=pkh, kw=pkw, stride_h=psh, stride_w=psw,
            a_scale=out_scale, out_scale=out_scale))

    # FC
    fc_w = model.fc.weight.detach().numpy()
    fc_b = model.fc.bias.detach().numpy()
    fq, f_scale = quantize_weights(fc_w)
    a_scale_fc = a_scales[-1]
    f_bias_q = np.round(fc_b / (f_scale * a_scale_fc)).astype(np.int32)
    fwb, fbb = int(fq.nbytes), int(f_bias_q.nbytes)
    blobs.append(fq.tobytes())
    blobs.append(f_bias_q.tobytes())
    layers.append(dict(
        type="fc", in_features=int(fc_w.shape[1]), out_features=int(fc_w.shape[0]),
        w_offset=offset, w_len=int(fq.size),
        b_offset=offset + fwb, b_len=int(f_bias_q.size),
        w_scale=f_scale, a_scale=a_scale_fc, out_scale=0.0))
    offset += fwb + fbb

    with open(OUT_DIR / "lprnet_sw.bin", "wb") as f:
        for b in blobs:
            f.write(b)

    meta = dict(input_h=IMG_H, input_w=IMG_W, classes=NUM_CLASSES,
                timesteps=7, bin_size=offset, layers=layers)
    (OUT_DIR / "lprnet_sw.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

# 生成 C 头文件
    L = []
    L.append("/* 自动生成：AE350 软件推理用 LPRNet 层描述（int8 权重 + int32 bias） */")
    L.append("#ifndef LPRNET_SW_H")
    L.append("#define LPRNET_SW_H")
    L.append("#include <stdint.h>")
    L.append("")
    L.append(f"#define LPRNET_IN_H      {IMG_H}")
    L.append(f"#define LPRNET_IN_W      {IMG_W}")
    L.append(f"#define LPRNET_CLASSES   {NUM_CLASSES}")
    L.append(f"#define LPRNET_TIMESTEPS 7")
    L.append(f"#define LPRNET_BIN_SIZE  {offset}")
    L.append(f"#define LPRNET_NUM_LAYERS {len(layers)}")
    L.append("")
    L.append("typedef struct {")
    L.append("    uint8_t  type;           /* 0=conv 1=pool 2=fc */")
    L.append("    uint16_t in_ch;          /* conv: 输入通道 / fc: in_features */")
    L.append("    uint16_t out_ch;         /* conv: 输出通道 / fc: out_features */")
    L.append("    uint8_t  kh, kw, stride_h, stride_w, pad;")
    L.append("    uint32_t w_offset, w_len, b_offset, b_len;")
    L.append("    float    w_scale, a_scale, out_scale;")
    L.append("} lprnet_layer_t;")
    L.append("")
    L.append(f"static const lprnet_layer_t LPRNET_LAYERS[{len(layers)}] = {{")
    for d in layers:
        if d["type"] == "conv":
            L.append(
                f"    {{0, {d['in_ch']}, {d['out_ch']}, {d['kh']}, {d['kw']}, "
                f"{d['stride_h']}, {d['stride_w']}, {d['pad']}, "
                f"{d['w_offset']}u, {d['w_len']}u, {d['b_offset']}u, {d['b_len']}u, "
                f"{d['w_scale']:.9f}f, {d['a_scale']:.9f}f, {d['out_scale']:.9f}f}},")
        elif d["type"] == "pool":
            L.append(
                f"    {{1, 0, 0, {d['kh']}, {d['kw']}, {d['stride_h']}, {d['stride_w']}, 0, "
                f"0u, 0u, 0u, 0u, 0.0f, {d['a_scale']:.9f}f, {d['out_scale']:.9f}f}},")
        else:
            L.append(
                f"    {{2, {d['in_features']}, {d['out_features']}, 0, 0, 1, 1, 0, "
                f"{d['w_offset']}u, {d['w_len']}u, {d['b_offset']}u, {d['b_len']}u, "
                f"{d['w_scale']:.9f}f, {d['a_scale']:.9f}f, 0.0f}},")
    L.append("};")
    L.append("")
    L.append("/* 软件推理接口（实现在 lprnet_sw.c） */")
    L.append("void lprnet_sw_init(const uint8_t *bin, uint32_t bin_size);")
    L.append("/* 输入 32*128 uint8 灰度，输出 7 个字符类别下标（0..38）。")
    L.append("   work0/work1 为两个工作缓冲，各 >= 32*32*128 = 131072 字节。 */")
    L.append("void lprnet_sw_infer(const uint8_t *img32x128, uint8_t out_cls[7], int32_t *out_scores,")
    L.append("                     uint8_t *work0, uint8_t *work1);")
    L.append("")
    L.append("#endif")
    (OUT_DIR / "lprnet_sw.h").write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"已导出 {OUT_DIR / 'lprnet_sw.bin'}（{offset} 字节）")
    print(f"已导出 {OUT_DIR / 'lprnet_sw.h'}（{len(layers)} 层）")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
