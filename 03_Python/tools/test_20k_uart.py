#!/usr/bin/env python3
# coding: utf-8
"""
20K 串口发送测试 —— 验证 20K 到底有没有往外发数据

用途：
  串口助手没有 230400 也能测；还能自动猜波特率。

用法（不需要任何参数）：
    D:\\Miniconda\\envs\\d2l\\python.exe test_20k_uart.py

接线（重要）：
  把 20K 的 M11(TX) 接到 USB-TTL 模块的 RX，GND 与 20K 共地。
  （如果 M11 还接着 Zynq 的 T19，也可以并联一根线到 USB-TTL 的 RX，
    但更稳的做法是暂时拔掉 Zynq 那一端。）

它会做的：
  1. 列出所有串口
  2. 依次按 115200 / 230400 / 921600 各收 3 秒
  3. 报告每个波特率收到多少字节、出现几个 AA 55 帧头
  4. 打印命中数据的十六进制片段
"""
from __future__ import annotations

import sys
import time

# 顶部开关
PORT = ""            # 留空=自动找；也可以写死 "COM5"
BAUDS = [230400, 115200, 921600, 460800]   # 依次尝试的波特率
SECONDS_EACH = 3.0   # 每个波特率抓多少秒

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("缺少 pyserial，请先 pip install pyserial", file=sys.stderr)
    sys.exit(2)

def show_ports():
    ports = list(list_ports.comports())
    if not ports:
        print("⚠️ 没有检测到任何串口！检查 USB-TTL 是否插好、驱动是否安装")
        return []
    print("可用串口：")
    for i, p in enumerate(ports):
        print(f"  [{i}] {p.device:<8} {p.description}")
    return ports

def pick_port(ports):
    if PORT:
        return PORT
    if len(ports) == 1:
        return ports[0].device
    for p in ports:
        t = f"{p.description} {p.manufacturer or ''}".upper()
        if "CH340" in t or "CH34" in t or "USB-SERIAL" in t or "CP210" in t:
            print(f"\n自动选择: {p.device}")
            return p.device
    try:
        idx = int(input("\n输入端口序号: ").strip())
        return ports[idx].device
    except (ValueError, IndexError):
        return ports[0].device if ports else None

def count_aa55(buf: bytes) -> int:
    n = 0
    for i in range(len(buf) - 1):
        if buf[i] == 0xAA and buf[i + 1] == 0x55:
            n += 1
    return n

def test_baud(port: str, baud: int, seconds: float):
    try:
        ser = serial.Serial(port, baud, timeout=0.1)
    except Exception as e:
        return {"baud": baud, "ok": False, "err": str(e), "n": 0, "hdr": 0, "head": b""}
    ser.reset_input_buffer()
    t0 = time.time()
    buf = bytearray()
    while time.time() - t0 < seconds:
        chunk = ser.read(8192)
        if chunk:
            buf.extend(chunk)
            if len(buf) > 200000:
                break
    ser.close()
    return {"baud": baud, "ok": True, "err": "",
            "n": len(buf), "hdr": count_aa55(bytes(buf)), "head": bytes(buf[:80])}

def main():
    print("=" * 58)
    print(" 20K 串口发送测试")
    print("=" * 58)
    ports = show_ports()
    if not ports:
        return 2
    port = pick_port(ports)
    if not port:
        return 2

    total_sec = SECONDS_EACH * len(BAUDS)
    print(f"\n>>> 使用 {port}，接下来 {total_sec:.0f} 秒")
    print(f">>> 请在这段时间内【反复按 20K 的拍照键】（每 1~2 秒按一次）")
    print(f">>> 依次尝试波特率: {BAUDS}\n")
    for i in range(3, 0, -1):
        print(f"    {i}...", end="\r")
        time.sleep(1)
    print("    开始！      ")

    results = []
    for b in BAUDS:
        print(f"  正在收 @{b} ...", end="", flush=True)
        r = test_baud(port, b, SECONDS_EACH)
        results.append(r)
        if not r["ok"]:
            print(f"  打不开: {r['err']}")
        else:
            print(f"  {r['n']} 字节, AA55×{r['hdr']}")

    print("\n" + "=" * 58)
    print(" 结果")
    print("=" * 58)
    best = None
    for r in results:
        if not r["ok"]:
            print(f"  @{r['baud']:<7}  打开失败: {r['err']}")
            continue
        flag = ""
        if r["hdr"] > 0:
            flag = "  ← ✅ 有 AA55 帧头！"
            best = r
        elif r["n"] > 0:
            flag = "  ← 有数据但无 AA55"
        else:
            flag = "  ← 无数据"
        print(f"  @{r['baud']:<7}  {r['n']:>7} 字节  AA55×{r['hdr']:>3}{flag}")

    print()
    if best:
        print(f"✅ 20K 在 @{best['baud']} 正常发送！")
        print(f"   开头字节(hex): {best['head'][:40].hex(' ')}")
        print()
        print(f"   → 那 Zynq 那边也必须配成 {best['baud']}")
        print(f"   → 现在 Zynq 的 AXI UART Lite 是 230400，如果这里显示 {best['baud']}")
        print(f"     且不等于 230400，就是波特率不匹配")
    elif any(r["ok"] and r["n"] > 0 for r in results):
        print("⚠️ 收到了数据，但都不像 AA55 帧")
        print("   可能：波特率都猜错了 / 线接到了 Zynq 那端 / 信号干扰")
        for r in results:
            if r["ok"] and r["head"]:
                print(f"   @{r['baud']} 前 20 字节: {r['head'][:20].hex(' ')}")
    else:
        print("❌ 所有波特率都收不到任何数据")
        print("   说明 20K 根本没往外发，或者：")
        print("   1. TX 线没接到 USB-TTL 的 RX")
        print("   2. 没共地（GND 必须接一起）")
        print("   3. 按键没按 / 摄像头没出图（LED 只停在 armed）")
        print("   4. 选错串口了")
    return 0

if __name__ == "__main__":
    sys.exit(main())
