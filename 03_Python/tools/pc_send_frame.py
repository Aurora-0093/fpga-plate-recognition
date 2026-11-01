#!/usr/bin/env python3
"""把测试图片按 AA55 协议发给 Zynq-7020 板，读回识别结果。

用法（在任意目录）：
    D:\\Miniconda\\envs\\d2l\\python.exe pc_send_frame.py --port COMx
    D:\\Miniconda\\envs\\d2l\\python.exe pc_send_frame.py --port COMx --dir <图片目录> --n 20
    D:\\Miniconda\\envs\\d2l\\python.exe pc_send_frame.py --port COMx --image <单张图>

协议：AA 55 + 4096 字节灰度(128x32 逐行) + 0D 0A，115200 8N1
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

IMG_W, IMG_H = 128, 32
DEFAULT_DIR = Path(r"D:\fpga_plate_recognition\plate_project\aa55_capture")

# ★ 测试开关：改下面这几行，然后直接运行本文件即可（不用命令行参数）
PORT = ""                       # 串口；留空 = 自动找 CH340
BAUD = 921600
DIR = DEFAULT_DIR               # 图片目录
IMAGE = None                    # 单张图路径；非 None 时优先用这张
N = 10                          # 发几张
COLOR = -1                      # 附加颜色字节 0~3；-1=不发
DIST = -1                       # 附加距离(mm)；-1=不发
TIMEOUT = 30.0                  # 等结果秒数

def load_gray(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return cv2.resize(img, (IMG_W, IMG_H))

def auto_port() -> str | None:
    """自动找 CH340 串口（没有就返回唯一的那个口，再没有返回 None）"""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    ports = list(list_ports.comports())
    if not ports:
        return None
    for p in ports:
        text = f"{p.device} {p.description} {p.manufacturer or ''}".upper()
        if "CH340" in text or "CH34" in text or "USB-SERIAL" in text:
            return p.device
    return ports[0].device if len(ports) == 1 else None

def main() -> int:
    try:
        import serial
    except ImportError:
        print("缺少 pyserial", file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="板子的 COM 口（不填自动找 CH340）")
    ap.add_argument("--baud", type=int, default=BAUD)
    ap.add_argument("--dir", type=Path, default=DIR)
    ap.add_argument("--image", type=Path, default=IMAGE)
    ap.add_argument("--n", type=int, default=N)
    ap.add_argument("--timeout", type=float, default=TIMEOUT, help="等待 PLATE 结果的秒数")
    ap.add_argument("--color", type=int, default=COLOR,
                    help="附加颜色字节(0/1/2/3)，-1=不发（发送 4100 基础帧）")
    ap.add_argument("--dist", type=int, default=DIST,
                    help="附加距离(mm)，-1=不发；给了就发 16 位大端")
    args, _unknown = ap.parse_known_args()   # 容忍 IDE/Jupyter 传进来的多余参数

    if not args.port:
        args.port = PORT or auto_port()
        if not args.port:
            print("没找到串口，请改文件顶部 PORT，或 --port COMx 指定", file=sys.stderr)
            return 2
        print(f"自动选择串口: {args.port}")

    if args.image:
        files = [args.image]
    else:
        files = sorted(p for p in args.dir.iterdir()
                       if p.suffix.lower() in (".jpg", ".jpeg", ".png"))[:args.n]
    if not files:
        print("没有图片", file=sys.stderr)
        return 2

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    ser.reset_input_buffer()
    print(f"已连接 {args.port} @{args.baud}，共 {len(files)} 张")

    ok = 0
    ms_list = []
    neon_list = []
    for i, p in enumerate(files, 1):
        gray = load_gray(p)
        if gray is None:
            print(f"{p.name}: 读取失败")
            continue

        trailer = b""
        if args.color >= 0:
            trailer += bytes([args.color & 0xFF])
        if args.dist >= 0:
            trailer += bytes([(args.dist >> 8) & 0xFF, args.dist & 0xFF])
        frame = b"\xAA\x55" + gray.tobytes() + trailer + b"\x0D\x0A"
        ser.write(frame)
        ser.flush()
        print(f"[{i}/{len(files)}] 发送 {p.name} ({len(frame)} 字节) ... ", end="", flush=True)

        # 等待 "PLATE:" 和可选的 "INFO:"
        t0 = time.time()
        buf = b""
        got = None
        info = None
        infer_ms = None
        neon = None
        while time.time() - t0 < args.timeout:
            chunk = ser.read(256)
            if not chunk:
                continue
            buf += chunk
            if b"TIME:" in buf and infer_ms is None:
                infer_ms = buf.split(b"TIME:", 1)[1].split(b"\r\n", 1)[0].decode("utf-8", errors="ignore").strip()
            if b"NEON=" in buf and neon is None:
                neon = buf.split(b"NEON=", 1)[1].split(b"\r\n", 1)[0].decode("utf-8", errors="ignore").strip()
            if b"PLATE:" in buf and got is None:
                got = buf.split(b"PLATE:", 1)[1].split(b"\r\n", 1)[0].decode("utf-8", errors="ignore").strip()
            if b"INFO:" in buf and got is not None:
                info = buf.split(b"INFO:", 1)[1].split(b"\r\n", 1)[0].decode("utf-8", errors="ignore").strip()
                break
        if got is None:
            print("超时（没收到结果）")
            continue
        line = f"识别: {got}"
        if info:
            line += f"    INFO: {info}"
        if infer_ms:
            line += f"    推理耗时: {infer_ms}"
        if neon:
            line += f"    NEON: {neon}"
        print(line)
        ok += 1
        if infer_ms:
            try:
                ms_list.append(float(infer_ms.lower().replace("ms", "").strip()))
            except ValueError:
                pass
        if neon:
            neon_list.append(neon.upper())

    ser.close()

# 汇总
    print("\n" + "=" * 56)
    print(f" 完成: {ok}/{len(files)} 张收到识别结果")
    if ms_list:
        # 首帧含一次性 NEON 自检（标量对比），统计时排除
        warm = ms_list[0]
        steady = ms_list[1:] if len(ms_list) > 1 else ms_list
        avg = sum(steady) / len(steady)
        print(f" 首帧 {warm:.0f} ms (含 NEON 自检, 仅一次)")
        print(f" 稳定推理: 平均 {avg:.0f} ms   最快 {min(steady):.0f} ms   最慢 {max(steady):.0f} ms")
        ref = 2500.0
        print(f" 对比纯标量版({ref:.0f}ms): 快 {ref/avg:.1f} 倍")
    if neon_list:
        m = neon_list.count("MATCH")
        print(f" NEON 一致性: {m}/{len(neon_list)} MATCH" + ("  ✅" if m == len(neon_list) else "  ⚠️ 有不一致"))
    print("=" * 56)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
