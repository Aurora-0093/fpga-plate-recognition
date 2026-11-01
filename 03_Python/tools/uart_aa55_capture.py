#!/usr/bin/env python3
"""接收 FPGA（Tang Primer 20K 整合版 v3.3）通过 UART 发出的 AA 55 灰度帧，保存 PNG 并可选直接推理。

FPGA 端帧格式（固定长度，v3.3）：
    AA 55 + 4096 个灰度像素(128x32，逐行) + 距离高字节 + 距离低字节 + 0D 0A  == 共 4102 字节
    距离 = 16 位无符号整数，大端（高字节在前），单位 mm；距离为 0 表示本帧没测到。
    波特率 115200（FPGA 端 27MHz / 234 ≈ 115384）。

链路：FPGA 按键触发一次 -> 采集裁剪缩放后的 128x32 灰度图 -> 串口发一帧。
本脚本循环收帧，校验帧尾 0D 0A，保存 PNG，可用 --infer 直接跑 lprnet.onnx，
并解析距离字节（mm -> cm）。

用法：
    python uart_aa55_capture.py                     # 连续收图（默认端口自动选择）
    python uart_aa55_capture.py --port COM8         # 指定串口
    python uart_aa55_capture.py --infer             # 每帧顺便跑 lprnet.onnx 推理
    python uart_aa55_capture.py --frames 1          # 只收 1 帧
    python uart_aa55_capture.py --ascii --no-display  # 无 GUI 环境
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import NamedTuple

# 三种帧格式，read_frame 会自动识别
# v3.2 颜色帧：AA 55 + 4096 像素 + 颜色字节 + 0D 0A                    == 4101 字节
# v3.3 距离帧：AA 55 + 4096 像素 + 距离H + 距离L + 0D 0A               == 4102 字节
# 合并帧：     AA 55 + 4096 像素 + 颜色字节 + 距离H + 距离L + 0D 0A    == 4103 字节
FRAME_BYTES_COLOR = 4101
FRAME_BYTES_DIST = 4102
FRAME_BYTES_FULL = 4103
FRAME_BYTES = FRAME_BYTES_FULL          # 兼容旧代码（最长帧）
PIXEL_BYTES = 4096                      # 像素字节数
COLOR_IDX = 4098                        # 颜色字节（color / full）
DIST_H_IDX = 4098                       # 距离高字节（dist）
DIST_L_IDX = 4099                       # 距离低字节（dist）
FULL_DIST_H_IDX = 4099                  # 距离高字节（full）
FULL_DIST_L_IDX = 4100                  # 距离低字节（full）
IMG_W, IMG_H = 128, 32                  # 图像尺寸
HEADER = b"\xAA\x55"
TAIL = b"\x0D\x0A"

# 与 3_train.py / bring_up.c 一致的字符表（41 类：36 字母数字 + 沪陕粤贵赣）
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ沪陕粤贵赣"

# 没有颜色信息时的默认显示
DEFAULT_COLOR = "蓝色"
DEFAULT_VEHICLE = "普通油车"

# 车牌颜色字节 → 颜色名 / 车型（v3.2 帧用）
# 00 = 默认（未识别也按蓝色显示，和 FPGA 端 color_flag=0 对应）
PLATE_COLOR = {0: "蓝色", 1: "黄色", 2: "蓝色", 3: "绿色"}
VEHICLE_TYPE = {0: "普通油车", 1: "大型车", 2: "普通油车", 3: "电车"}

class Frame(NamedTuple):
    """一帧解析结果：color 只有颜色帧/合并帧有，dist_mm 只有距离帧/合并帧有。"""
    pixels: bytes
    color: int | None      # 颜色字节（0/1/2/3），无该字段时为 None
    dist_mm: int | None    # 距离（mm），无该字段时为 None

def color_of(color: int | None = None) -> str:
    """颜色字节 → 颜色名；None（v3.3 无颜色）→ 默认蓝色。"""
    if color is None:
        return DEFAULT_COLOR
    return PLATE_COLOR.get(color, DEFAULT_COLOR)

def vehicle_of(color: int | None = None) -> str:
    """颜色字节 → 车型；None（v3.3 无颜色）→ 默认普通油车。"""
    if color is None:
        return DEFAULT_VEHICLE
    return VEHICLE_TYPE.get(color, DEFAULT_VEHICLE)

def dist_cm(dist_mm: int | None) -> float | None:
    """距离（mm）→ 厘米；None 或 0 返回 None（无效/未测到）。"""
    if not dist_mm:
        return None
    return round(dist_mm / 10.0, 1)

# 是否跑推理的总开关：False = 只收图保存（默认，先采集数据）；
# True = 每帧顺带跑 lprnet.onnx 推理。命令行 --infer / --no-infer 可覆盖本开关。
RUN_INFER = True

RAMP = " .:-=+*#%@"

def render_ascii(pixels: bytes) -> str:
    step = max(1, IMG_W // 96)
    lines = []
    for y in range(0, IMG_H, max(1, IMG_H // 24)):
        row = []
        for x in range(0, IMG_W, step):
            v = pixels[y * IMG_W + x]
            row.append(RAMP[v * (len(RAMP) - 1) // 255])
        lines.append("".join(row))
    return "\n".join(lines)

class AA55FrameReader:
    """按 AA 55 帧头同步读帧，**自动识别**三种帧：
       color(4101, 颜色) / dist(4102, 距离) / full(4103, 颜色+距离)

    mode 可选 "auto"（默认）/ "color" / "dist" / "full"（强制某一种）。
    返回 Frame(pixels, color, dist_mm)：没有的字段为 None。
    """

    def __init__(self, serial_port, mode: str = "auto"):
        self.serial = serial_port
        self.mode = mode
        self.buffer = bytearray()
        self.total_bytes = 0
        self.first_bytes = bytearray()
        self.resyncs = 0
        self.last_mode = ""          # 最近一次识别到的帧格式

    def _pick(self, n: int):
        """按缓冲长度 + 帧尾位置判断帧格式，返回 (kind, size) 或 (None, 0)。

        顺序必须从长到短：full(4103) -> dist(4102) -> color(4101)，
        避免 4103 帧在 4101 字节时的帧尾巧合误判。
        """
        modes = ["full", "dist", "color"] if self.mode == "auto" else [self.mode]
        size_map = {"color": FRAME_BYTES_COLOR, "dist": FRAME_BYTES_DIST, "full": FRAME_BYTES_FULL}
        for m in modes:
            size = size_map[m]
            if n >= size and self.buffer[size - 2] == TAIL[0] and self.buffer[size - 1] == TAIL[1]:
                return m, size
        return None, 0

    def read_frame(self, timeout_s: float):
        # timeout_s <= 0 表示无限等待（连续监听模式）
        deadline = None if timeout_s <= 0 else time.monotonic() + timeout_s
        while deadline is None or time.monotonic() < deadline:
            # 1) 丢弃帧头前的杂乱字节
            idx = self.buffer.find(HEADER)
            if idx < 0:
                if len(self.buffer) > len(HEADER) - 1:
                    del self.buffer[: -(len(HEADER) - 1)]
            elif idx:
                self.resyncs += 1
                del self.buffer[:idx]

            # 2) 缓冲区以帧头开始时，自动识别帧格式并校验帧尾
            if self.buffer.startswith(HEADER):
                kind, size = self._pick(len(self.buffer))
                if kind:
                    pixels = bytes(self.buffer[2 : 2 + PIXEL_BYTES])
                    if kind == "color":
                        color = self.buffer[COLOR_IDX]
                        dist = None
                    elif kind == "dist":
                        color = None
                        dist = (self.buffer[DIST_H_IDX] << 8) | self.buffer[DIST_L_IDX]
                    else:  # full
                        color = self.buffer[COLOR_IDX]
                        dist = (self.buffer[FULL_DIST_H_IDX] << 8) | self.buffer[FULL_DIST_L_IDX]
                    del self.buffer[:size]
                    self.last_mode = kind
                    return Frame(pixels, color, dist)

                # 已收够最长帧(4103)还不匹配 → 误同步，丢 1 字节重新找帧头
                if len(self.buffer) >= FRAME_BYTES_FULL:
                    self.resyncs += 1
                    del self.buffer[0]
                    continue

            # 3) 继续读串口
            waiting = getattr(self.serial, "in_waiting", 0)
            chunk = self.serial.read(max(1, min(waiting or 1, 65536)))
            if chunk:
                self.buffer.extend(chunk)
                self.total_bytes += len(chunk)
                need = 256 - len(self.first_bytes)
                if need > 0:
                    self.first_bytes.extend(chunk[:need])
        return None

def choose_port(requested: str | None) -> str:
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    if requested:
        return requested
    if not ports:
        raise RuntimeError("没有找到串口；请接好板子或传 --port COMx")
    if len(ports) == 1:
        print(f"自动选择 {ports[0].device}: {ports[0].description}")
        return ports[0].device
    print("可用串口:")
    for index, item in enumerate(ports, 1):
        print(f"  {index}. {item.device}: {item.description}")
    selection = int(input("选择串口编号: ").strip()) - 1
    if not 0 <= selection < len(ports):
        raise RuntimeError("无效的串口编号")
    return ports[selection].device

def load_ort_session(model_path: Path):
    try:
        import onnxruntime as ort
    except ImportError:
        print("缺少 onnxruntime（pip install onnxruntime），已跳过推理。", file=sys.stderr)
        return None
    if not model_path.is_file():
        print(f"找不到模型 {model_path}（可先运行 5_export.py 导出 lprnet.onnx），已跳过推理。",
              file=sys.stderr)
        return None
    try:
        return ort.InferenceSession(str(model_path))
    except Exception as exc:  # noqa: BLE001
        print(f"加载模型失败: {exc}", file=sys.stderr)
        return None

def infer(session, pixels: bytes) -> str:
    import numpy as np

    img = np.frombuffer(pixels, dtype=np.uint8).reshape(IMG_H, IMG_W).astype(np.float32) / 255.0
    x = img[np.newaxis, np.newaxis, :, :]  # (1, 1, 32, 128)
    input_name = session.get_inputs()[0].name
    output = session.run(None, {input_name: x})[0]
    idxs = np.asarray(output).squeeze(0).argmax(axis=1)
    return "".join(CHARS[int(i)] for i in idxs)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="接收 FPGA AA 55 灰度帧（128x32）并保存/推理。")
    parser.add_argument("--port", help="串口，如 COM8；只有一个串口时自动选择")
    parser.add_argument("--baud", type=int, default=115200,
                        help="波特率（默认 115200，与 FPGA 的 27MHz/234 一致）")
    parser.add_argument("--frames", type=int, default=0,
                        help="接收帧数；0 表示一直收到 Ctrl+C（默认）")
    parser.add_argument("--timeout", type=float, default=0.0,
                        help="连续模式下每帧等待秒数；0 表示无超时一直监听（默认）")
    parser.add_argument("--output", type=Path, default=Path("aa55_capture"),
                        help="图片输出目录")
    parser.add_argument("--infer", action="store_true",
                        help="每帧用 lprnet.onnx 推理并打印车牌（覆盖 RUN_INFER 开关）")
    parser.add_argument("--no-infer", action="store_true",
                        help="只收图不推理（覆盖 RUN_INFER 开关）")
    parser.add_argument("--model", type=Path, default=Path("lprnet.onnx"), help="ONNX 模型路径")
    parser.add_argument("--frame-mode", choices=["auto", "color", "dist", "full"], default="auto",
                        help="帧格式：auto 自动识别（默认）/ color 强制 v3.2 颜色帧 / dist 强制 v3.3 距离帧")
    parser.add_argument("--ascii", action="store_true", help="在终端打印 ASCII 预览")
    parser.add_argument("--no-display", action="store_true", help="不弹预览窗口（默认不弹）")
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    try:
        import serial
        from PIL import Image
    except ImportError:
        print("缺少依赖（pip install pyserial pillow onnxruntime）", file=sys.stderr)
        return 2

    # 推理开关优先级：--infer > --no-infer > RUN_INFER
    do_infer = RUN_INFER
    if args.no_infer:
        do_infer = False
    if args.infer:
        do_infer = True
    session = load_ort_session(args.model) if do_infer else None

    try:
        port = choose_port(args.port)
        args.output.mkdir(parents=True, exist_ok=True)
        with serial.Serial(port, args.baud, timeout=0.05) as ser:
            ser.reset_input_buffer()
            reader = AA55FrameReader(ser, mode=args.frame_mode)
            print(f"监听 {port} @ {args.baud} baud。帧格式自动识别："
                  f"v3.2 颜色帧(4101B) / v3.3 距离帧(4102B)。")
            print("在 FPGA 板上按一下按键即可收到一帧（整合版：定位失败时发固定裁剪框）。")
            if session is not None:
                print(f"推理已开启：每帧用 {args.model} 推理并打印车牌。")
            else:
                print("推理已关闭（只收图保存）。要开推理：加 --infer，或把 RUN_INFER 设为 True。")
            saved = 0
            while args.frames == 0 or saved < args.frames:
                frame = reader.read_frame(args.timeout)
                if frame is None:
                    if args.frames == 0:
                        continue  # 连续监听，静默等待下一帧
                    print(f"超时未收到完整帧（共收 {reader.total_bytes} 字节）。"
                          "检查：板子是否已下载整合版位流、TX-RX 接线与共地、按键触发。",
                          file=sys.stderr)
                    head = bytes(reader.first_bytes[:64])
                    if head:
                        print("  前 64 字节 HEX: " +
                              " ".join(f"{b:02X}" for b in head), file=sys.stderr)
                    return 1
                pixels, color, dist_mm = frame
                saved += 1
                image = Image.frombytes("L", (IMG_W, IMG_H), pixels)
                output_path = args.output / f"gray_{saved:04d}_{IMG_W}x{IMG_H}.jpg"
                image.save(output_path)
                vmin, vmax = min(pixels), max(pixels)
                mean = sum(pixels) / len(pixels)
                parts = []
                if color is not None:
                    parts.append(f"颜色={color_of(color)}")
                    parts.append(f"车型={vehicle_of(color)}")
                if dist_mm is not None:
                    parts.append(f"距离={dist_cm(dist_mm):.1f}cm" if dist_mm else "距离=未测到")
                info = (" " + "  ".join(parts)) if parts else ""
                print(f"帧 {saved}:{info} "
                      f"min={vmin} max={vmax} mean={mean:.1f} -> {output_path.name}")
                if session is not None:
                    plate = infer(session, pixels)
                    print(f"  识别结果: {plate}  车型: {vehicle_of(color)}  颜色: {color_of(color)}")
                if args.ascii:
                    print(render_ascii(pixels))
            print(f"共收到 {saved} 帧，已保存到 {args.output}/。")
            return 0
    except serial.SerialException as exc:
        print(f"串口错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
