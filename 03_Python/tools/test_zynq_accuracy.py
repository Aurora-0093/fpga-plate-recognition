"""批量测试 Zynq 板识别准确率：从文件名解析真实车牌，和板子返回的对比。"""
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import serial

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ沪陕粤贵赣"
PINYIN = {"hu": "沪", "shan": "陕", "yue": "粤", "gui": "贵", "gan": "赣"}

# ★ 测试开关：改下面这几行，然后直接运行本文件即可
TEST_DIR = Path(r"D:\fpga_plate_recognition\plate_project\split\test")
PORT = "COM3"                   # Zynq 串口
N = 20                          # 测几张（前 N 张）
EVERY_KTH = 1                   # 每隔 K 张取 1 张（1=连续取，N 大时可跨车牌抽样）

def truth_from_name(name: str) -> str:
    """gan_DF0002_10_0000.jpg -> 赣DF0002"""
    m = re.match(r"([a-z]+)_([A-Z0-9]+)_", name)
    if not m:
        return ""
    return PINYIN.get(m.group(1), "") + m.group(2)

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ser = serial.Serial(PORT, 115200, timeout=0.3)
    ser.reset_input_buffer()
    all_files = sorted(f for f in TEST_DIR.iterdir() if f.suffix.lower() in (".jpg", ".png"))
    files = all_files[::EVERY_KTH][:N]

    ok = 0
    print(f"{'文件名':<32} {'真实':<12} {'识别':<14} 结果")
    print("-" * 78)
    for f in files:
        img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        gray = cv2.resize(img, (128, 32))
        ser.write(b"\xAA\x55" + gray.tobytes() + b"\x0D\x0A")
        ser.flush()
        buf = b""
        t0 = time.time()
        while time.time() - t0 < 10:
            c = ser.read(256)
            if c:
                buf += c
                if b"INFO:" in buf:
                    break
        got = ""
        if b"PLATE:" in buf:
            got = buf.split(b"PLATE:", 1)[1].split(b"\r\n", 1)[0].decode("utf-8", errors="ignore")
            got = got.split(",")[0]
        truth = truth_from_name(f.name)
        good = got == truth
        ok += good
        print(f"{f.name[:32]:<32} {truth:<12} {got:<14} {'OK' if good else 'NG'}")
    ser.close()
    print("-" * 78)
    print(f"准确率: {ok}/{len(files)} = {ok / max(1, len(files)) * 100:.1f}%")

if __name__ == "__main__":
    main()
