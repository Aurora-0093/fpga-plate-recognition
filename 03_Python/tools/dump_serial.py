#!/usr/bin/env python3
"""串口原始数据诊断：看板子到底发了什么

用法（不用任何参数，直接跑）：
    D:\\Miniconda\\envs\\d2l\\python.exe dump_serial.py
然后按 20K 的拍照键，观察输出。

它会统计：
  - 收到多少字节
  - 出现几次 AA 55 帧头
  - 出现哪些文本行（PLATE / PLATE2 / IMG / IMG2 / TIME / waiting）
"""
from __future__ import annotations
import sys
import time
from collections import Counter

# 顶部开关
PORT = ""          # 留空自动找 CH340
BAUD = 921600
SECONDS = 30       # 抓多少秒

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("缺少 pyserial", file=sys.stderr)
    sys.exit(2)

def auto_port():
    ports = list(list_ports.comports())
    if not ports:
        return None
    for p in ports:
        t = f"{p.device} {p.description} {p.manufacturer or ''}".upper()
        if "CH340" in t or "CH34" in t or "USB-SERIAL" in t:
            return p.device
    return ports[0].device if len(ports) == 1 else None

def main():
    port = PORT or auto_port()
    if not port:
        print("没找到串口，请改文件顶部 PORT")
        return 2
    print(f"打开 {port} @{BAUD}，抓 {SECONDS} 秒...")
    print(">>> 现在去按 20K 的拍照键 <<<")
    print()

    ser = serial.Serial(port, BAUD, timeout=0.1)
    ser.reset_input_buffer()

    t0 = time.time()
    total = 0
    buf = bytearray()
    lines = Counter()
    first_bytes = None

    while time.time() - t0 < SECONDS:
        chunk = ser.read(4096)
        if not chunk:
            continue
        if first_bytes is None:
            first_bytes = chunk[:64]
        total += len(chunk)
        buf.extend(chunk)
        # 抽文本行统计（只从可打印段里找）
        text = bytes(b if 32 <= b < 127 else 10 for b in chunk).decode("ascii", "ignore")
        for ln in text.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            for key in ("waiting frame", "PLATE:", "PLATE2:", "INFO:", "INFO2:",
                        "IMG:", "IMG2:", "TIME:", "DBG:", "LPRNet", "["):
                if ln.startswith(key):
                    lines[ln[:60]] += 1
                    break

    ser.close()
    el = time.time() - t0

    print(f"\n===== 抓包结果（{el:.1f} 秒）=====")
    print(f"总字节数: {total}   ({total/el:.0f} 字节/秒)")

    n_aa55 = 0
    for i in range(len(buf) - 1):
        if buf[i] == 0xAA and buf[i + 1] == 0x55:
            n_aa55 += 1
    print(f"AA 55 帧头出现: {n_aa55} 次")
    print(f"文本行种类: {len(lines)}")
    for ln, c in lines.most_common(15):
        print(f"   {c:>4} 次  {ln}")

    if first_bytes:
        print(f"\n开头 64 字节(hex):\n{first_bytes.hex(' ')}")

    print("\n===== 判读 =====")
    if total == 0:
        print("❌ 一个字节都没收到")
        print("   → Zynq 程序没跑（串口无输出），或波特率不对，或端口错")
    elif n_aa55 == 0 and not any(k.startswith(("PLATE", "waiting")) for k in lines):
        print("⚠️ 收到数据但既没有 AA55 也没有 PLATE 行")
        print("   → 可能是波特率不匹配产生的乱码")
    elif any(k.startswith("waiting") for k in lines) and not any(k.startswith("PLATE") for k in lines):
        print("⚠️ Zynq 一直在等帧，说明 20K 的数据没到 Zynq")
        print("   → 20K 的 TX 没接到 T19 / 没共地 / 20K 波特率与 Zynq 不匹配")
    elif any(k.startswith("PLATE") for k in lines):
        print("✅ 收到了 PLATE 行，Zynq 正常工作")
        if any(k.startswith("PLATE2") for k in lines):
            print("✅ 也收到了 PLATE2，双牌链路通了！")
        else:
            print("⚠️ 没有 PLATE2，第二帧没收到")
            print("   → 固件可能还是旧版，或第二帧超时太短")
    return 0

if __name__ == "__main__":
    sys.exit(main())
