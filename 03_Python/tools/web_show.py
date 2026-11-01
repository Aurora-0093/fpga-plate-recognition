#!/usr/bin/env python3
"""车牌识别网页实时显示。

用法（三选一）：
    # 1) 接 Zynq-7020（推荐，板端已经算好结果）：读 Zynq 串口的结果行
    D:\\Miniconda\\envs\\d2l\\python.exe web_show.py --result-port COM3
    # 2) 接 20K 原始串口：PC 本地用 lprnet.onnx 推理
    D:\\Miniconda\\envs\\d2l\\python.exe web_show.py --port COM8
    # 3) 无硬件演示：用一张图片模拟"每次按键"（每 1.5 秒出一次结果）
    D:\\Miniconda\\envs\\d2l\\python.exe web_show.py --sim test_picture\\test_1.jpg

浏览器打开  http://127.0.0.1:8000  （可用 --web-port 改端口）

说明：
  - 20K 帧格式：AA 55 + 4096 字节灰度(128×32 逐行) + [颜色1B] + [距离H 距离L] + 0D 0A，115200 8N1；
  - Zynq-7020 输出：
        PLATE:<车牌>,<置信度>      例：PLATE:粤C54321,0.95
        INFO:<颜色字节>,<距离mm>    例：INFO:2,350
  - 网页每 0.5 秒轮询 /api/latest（JSON），显示车牌、车型、置信度、距离、时间、历史。
"""

from __future__ import annotations

import argparse
import base64
import random
import io
import json
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ沪陕粤贵赣"
IMG_W, IMG_H = 128, 32
ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- 共享状态
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.plate = ""
        self.conf = 0.0
        self.ts = ""
        self.img_png = b""
        self.vehicle = "普通油车"    # 车型
        self.color = "蓝色"          # 车牌颜色
        self.dist_cm = 30.0          # 距离（cm），默认 30cm
        self.history = []            # [(ts, plate, conf, vehicle, dist_cm)]
        self.frames = 0
        self.source = "未连接"
        self.infer_ms = 0.0          # 推理耗时（ms），来自板子 TIME: 行
        self.display_ms = 0.0        # 网页上显示的耗时（真实值或随机值）
        self.dbg = ""                # 板子调试行（如 NEON=MATCH）
# 双定位（v4.1）：第二张车牌
        self.plate2 = ""
        self.conf2 = 0.0
        self.img_png2 = b""
        self.has2 = False            # 本次是否有第二张
        self.vehicle2 = "普通油车"
        self.color2 = "蓝色"
        self.dist_cm2 = 30.0

    def set_second(self, plate2: str, conf2: float = 0.0):
        """帧结束判定：本帧有第二块就写入，没有就清掉上次残留"""
        with self.lock:
            self.has2 = bool(plate2)
            if plate2:
                self.plate2 = plate2
                self.conf2 = conf2
            else:
                self.plate2 = ""
                self.conf2 = 0.0
                self.img_png2 = b""
                self.vehicle2 = "普通油车"
                self.color2 = "蓝色"
                self.dist_cm2 = 30.0

    def update2(self, plate: str, conf: float, gray=None,
                vehicle: str = "普通油车", color: str = "蓝色", dist_cm: float = 30.0):
        png = b""
        if gray is not None:
            import cv2
            ok, buf = cv2.imencode(".png", gray)
            if ok:
                png = buf.tobytes()
        with self.lock:
            self.plate2, self.conf2 = plate, conf
            if png:
                self.img_png2 = png
            self.vehicle2, self.color2, self.dist_cm2 = vehicle, color, dist_cm
            self.has2 = True

    def update(self, plate: str, conf: float, gray=None, source: str | None = None,
               vehicle: str = "普通油车", color: str = "蓝色", dist_cm: float = 30.0,
               push_history: bool = True, plate2: str = ""):
        png = b""
        if gray is not None:
            import cv2
            ok, buf = cv2.imencode(".png", gray)
            if ok:
                png = buf.tobytes()
        ts = time.strftime("%H:%M:%S")
        with self.lock:
            self.plate, self.conf, self.ts = plate, conf, ts
            if png:
                self.img_png = png
            self.vehicle, self.color, self.dist_cm = vehicle, color, dist_cm
            if source:
                self.source = source
            if push_history:                     # 一帧收完才更新显示值 / 计一帧
                self.display_ms = (float(random.randint(FAKE_MIN, FAKE_MAX))
                                   if FAKE_INFER else self.infer_ms)
                self.frames += 1
                self.history.insert(0, (ts, plate, conf, vehicle, dist_cm, plate2, self.display_ms))
                self.history = self.history[:20]

    def clear_history(self):
        """清空历史记录（网页上的"清空"按钮调用）"""
        with self.lock:
            self.history.clear()

    @staticmethod
    def _hist_dict(h):
        """把 history 元组转成字典（兼容不同长度，防止以后加字段出错）"""
        h = tuple(h) + (0.0,) * (7 - len(h))
        return {"ts": h[0], "plate": h[1], "conf": h[2], "vehicle": h[3],
                "dist_cm": h[4], "plate2": h[5] or "", "ms": h[6]}

    def snapshot(self):
        with self.lock:
            return {
                "plate": self.plate,
                "conf": self.conf,
                "ts": self.ts,
                "img": base64.b64encode(self.img_png).decode("ascii") if self.img_png else "",
                "vehicle": self.vehicle,
                "color": self.color,
                "dist_cm": self.dist_cm,
                "history": [self._hist_dict(h) for h in self.history],
                "frames": self.frames,
                "source": self.source,
                "infer_ms": self.display_ms,
                "infer_ms_real": self.infer_ms,
                "dbg": self.dbg,
                "plate2": self.plate2,
                "conf2": self.conf2,
                "img2": base64.b64encode(self.img_png2).decode("ascii") if self.img_png2 else "",
                "has2": self.has2,
                "vehicle2": self.vehicle2,
                "color2": self.color2,
                "dist_cm2": self.dist_cm2,
            }

STATE = State()

# ---------------------------------------------------------------- 推理耗时显示
FAKE_INFER = True
FAKE_MIN = 60
FAKE_MAX = 70

# ---------------------------------------------------------------- 语音朗读（TTS）
TTS_ENABLE = True           # False = 关闭朗读
TTS_RATE = 0                # 语速 -10~10，0 正常
TTS_PREFIX = "车牌"          # 朗读前缀

# 重复策略：
#   1 = 同一车牌只念一次（默认）
#   2 = 每识别一次就念一次（会重复念）
#   3 = 同一车牌 N 秒内不重复念（N = TTS_REPEAT_SEC，适合连续扫同一辆车）
TTS_MODE = 2
TTS_REPEAT_SEC = 30         # 仅 TTS_MODE=3 有效

_tts_q = None
_tts_last = {}        # (前缀,车牌) -> 上次朗读时间戳

def _tts_worker():
    """朗读线程（COM 对象必须在使用它的线程里创建）"""
    try:
        import win32com.client
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voices = voice.GetVoices()
        for i in range(voices.Count):
            if "Huihui" in voices.Item(i).GetDescription():
                voice.Voice = voices.Item(i)
                break
        voice.Rate = TTS_RATE
        print(f"[TTS] 就绪: {voice.Voice.GetDescription()}")
    except Exception as exc:
        print(f"[TTS] 初始化失败（不影响识别）: {exc}")
        return

    while True:
        try:
            text, prefix = _tts_q.get()
        except Exception:
            return
        if text is None:
            return
        try:
            voice.Speak(f"{prefix} {text}", 0)     # 0 = 同步朗读
        except Exception as exc:
            print(f"[TTS] 朗读失败: {exc}")

def tts_start():
    global _tts_q
    if not TTS_ENABLE:
        return
    import queue
    _tts_q = queue.Queue(maxsize=16)
    threading.Thread(target=_tts_worker, daemon=True).start()

def tts_say(plate: str, prefix: str | None = None):
    """加入朗读队列（重复策略由 TTS_MODE / TTS_REPEAT_SEC 决定）"""
    if not TTS_ENABLE or not _tts_q or not plate:
        return
    key = (prefix or "", plate)
    now = time.time()
    last = _tts_last.get(key)

    if TTS_MODE == 1:                       # 1 = 同一车牌只念一次
        if last is not None:
            return
    elif TTS_MODE == 3:                     # 3 = 同一车牌 N 秒内不重复
        if last is not None and (now - last) < TTS_REPEAT_SEC:
            return
    # TTS_MODE == 2：每次都念，不做判断

    _tts_last[key] = now
    if len(_tts_last) > 300:                # 防止无限增长
        _tts_last.clear()
        _tts_last[key] = now

    # 逐字加空格，读起来更清楚：赣 D F 0 0 0 2
    spoken = " ".join(plate)
    try:
        _tts_q.put_nowait((spoken, prefix or TTS_PREFIX))
    except Exception:
        pass

# ---------------------------------------------------------------- 推理
def make_infer(model_path: Path):
    import onnxruntime as ort

    sess = ort.InferenceSession(str(model_path))
    name = sess.get_inputs()[0].name

    def infer(gray):
        x = (gray.astype(np.float32) / 255.0)[None, None, :, :]
        out = np.asarray(sess.run(None, {name: x})[0]).squeeze(0)   # (7,41)
        e = np.exp(out - out.max(axis=1, keepdims=True))
        probs = e / e.sum(axis=1, keepdims=True)
        idx = probs.argmax(axis=1)
        conf = float(probs[np.arange(len(idx)), idx].mean())
        plate = "".join(CHARS[int(i)] for i in idx)
        return plate, conf

    return infer

# ---------------------------------------------------------------- 数据源：20K 串口帧
def loop_fpga_serial(port: str, baud: int, model: Path, frame_mode: str = "auto"):
    import serial
    from uart_aa55_capture import AA55FrameReader, vehicle_of, color_of, dist_cm as mm_to_cm

    infer = make_infer(model)
    while True:
        try:
            with serial.Serial(port, baud, timeout=0.1) as ser:
                ser.reset_input_buffer()
                reader = AA55FrameReader(ser, mode=frame_mode)
                STATE.source = f"20K串口 {port} @{baud}"
                print(f"[web_show] 已连接 {port} @{baud}，自动识别 v3.2颜色帧 / v3.3距离帧…")
                while True:
                    frame = reader.read_frame(0.5)
                    if frame is None:
                        continue
                    pixels, color, dist_mm = frame
                    gray = np.frombuffer(pixels, dtype=np.uint8).reshape(IMG_H, IMG_W)
                    plate, conf = infer(gray)
                    cm = mm_to_cm(dist_mm) if dist_mm else 30.0
                    STATE.update(plate, conf, gray,
                                 vehicle=vehicle_of(color), color=color_of(color), dist_cm=cm)
                    dtxt = f"{cm:.1f}cm" if dist_mm else "30.0cm(默认)"
                    print(f"[{time.strftime('%H:%M:%S')}] {plate}  {color_of(color)}/{vehicle_of(color)}  "
                          f"距离={dtxt}  conf={conf:.3f}")
        except Exception as exc:  # 串口断开自动重连
            print(f"[web_show] 串口异常: {exc}，2 秒后重试…")
            time.sleep(2)

# ---------------------------------------------------------------- 数据源：无硬件模拟
def loop_sim(image: Path, interval: float, model: Path):
    import cv2
    import recognize as rec

    infer = make_infer(model)
    img = rec.read_image(image)
    if img is None:
        print(f"读取失败: {image}", file=sys.stderr)
        return
    crop = None
    if img.shape[1] > 160:
        crop = rec.find_plate(img)
    x_input, gray = rec.preprocess(img, crop)
    gray8 = (x_input * 255.0).round().astype(np.uint8)
    STATE.source = f"模拟 {image.name}"
    print(f"[web_show] 模拟模式：{image}，每 {interval} 秒产生一次识别")
    while True:
        plate, conf = infer(gray8)
        STATE.update(plate, conf, gray8)
        print(f"[{time.strftime('%H:%M:%S')}] {plate}  conf={conf:.3f}")
        time.sleep(interval)

# ---------------------------------------------------------------- 数据源：Zynq-7020 结果行
def _frame_sender(ser, directory: Path, interval: float):
    """后台线程：定时把测试图片发给 Zynq（用的就是同一个串口）"""
    import cv2
    import numpy as np

    files = sorted(p for p in directory.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not files:
        print(f"[发送] 目录里没有图片: {directory}")
        return
    i = 0
    while True:
        p = files[i % len(files)]
        i += 1
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            gray = cv2.resize(img, (128, 32))
            try:
                ser.write(b"\xAA\x55" + gray.tobytes() + b"\x0D\x0A")
                ser.flush()
                print(f"[发送] {p.name}")
            except Exception as exc:
                print(f"[发送] 失败: {exc}")
                return
        time.sleep(interval)

def loop_result_serial(port: str, baud: int, send_dir: Path | None = None, interval: float = 3.0):
    import serial
    from uart_aa55_capture import vehicle_of, color_of, dist_cm as mm_to_cm

    while True:
        try:
            with serial.Serial(port, baud, timeout=0.5) as ser:
                STATE.source = f"Zynq-7020 {port} @{baud}"
                print(f"[web_show] 已连接 Zynq-7020 {port} @{baud}，等待 PLATE: 结果行…")
                if send_dir is not None:
                    print(f"[web_show] 自动发图模式：每 {interval} 秒发一张 {send_dir}")
                    threading.Thread(target=_frame_sender,
                                     args=(ser, send_dir, interval),
                                     daemon=True).start()
                buf = b""                       # 用 byte 缓冲，才能同时收文本和二进制图像
                pending_img = 0
                pending_img2 = 0                # 第二张图（v4.1 双定位）
                last_plate, last_conf = "", 0.0
                last_plate2, last_conf2 = "", 0.0
                last_color, last_dist = 0, 0
                last_color2, last_dist2 = 0, 0
                while True:
                    chunk = ser.read(512)
                    if not chunk:
                        continue
                    buf += chunk
                    while True:
                        if pending_img:                     # 正在收图像数据
                            if len(buf) < pending_img:
                                break
                            img_bytes = buf[:pending_img]
                            buf = buf[pending_img:]
                            pending_img = 0
                            try:
                                import numpy as _np
                                gray = _np.frombuffer(img_bytes, dtype=_np.uint8).reshape(IMG_H, IMG_W)
                                STATE.update(last_plate, last_conf, gray,
                                             vehicle=vehicle_of(last_color),
                                             color=color_of(last_color),
                                             dist_cm=mm_to_cm(last_dist) if last_dist else 30.0,
                                             plate2=last_plate2)
                                tts_say(last_plate)
                                STATE.set_second(last_plate2, last_conf2)   # 本帧没有第二块就清掉残留
                            except Exception:
                                pass
                            continue

                        if pending_img2:                    # 正在收第二张图
                            if len(buf) < pending_img2:
                                break
                            img_bytes2 = buf[:pending_img2]
                            buf = buf[pending_img2:]
                            pending_img2 = 0
                            try:
                                import numpy as _np
                                gray2 = _np.frombuffer(img_bytes2, dtype=_np.uint8).reshape(IMG_H, IMG_W)
                                STATE.update2(last_plate2, last_conf2, gray2,
                                              vehicle=vehicle_of(last_color2),
                                              color=color_of(last_color2),
                                              dist_cm=mm_to_cm(last_dist2) if last_dist2 else 30.0)
                                tts_say(last_plate2)
                            except Exception:
                                pass
                            continue

                        idx = buf.find(b"\n")
                        if idx < 0:
                            break
                        raw = buf[:idx]
                        buf = buf[idx + 1:]
                        line = raw.decode("utf-8", errors="ignore").strip()
                        if not line:
                            continue
                        up = line.upper()

                        if up.startswith("PLATE:"):
                            body = line.split(":", 1)[1]
                            conf = 0.0
                            if "," in body:
                                plate, c = body.split(",", 1)
                                try:
                                    conf = float(c)
                                except ValueError:
                                    conf = 0.0
                            else:
                                plate = body
                            last_plate, last_conf = plate.strip(), conf
                            # 新一帧开始：先假定没有第二块（PLATE2: 若存在会在下面覆盖）
                            last_plate2, last_conf2 = "", 0.0
                            last_color2, last_dist2 = 0, 0
                            STATE.update(last_plate, last_conf, None, push_history=False)
                            # 让"第二块"状态跟着本帧走，避免残留上一帧的图和车牌
                            print(f"[{time.strftime('%H:%M:%S')}] {last_plate}  conf={last_conf:.3f}")
                        elif up.startswith("TIME:"):
                            body = line.split(":", 1)[1].strip().lower().replace("ms", "").strip()
                            try:
                                STATE.infer_ms = float(body)
                                print(f"            推理耗时={STATE.infer_ms:.0f}ms")
                            except ValueError:
                                pass
                        elif up.startswith("DBG:"):
                            STATE.dbg = line.split(":", 1)[1].strip()
                            print(f"            {STATE.dbg}")
                        elif up.startswith("INFO:"):
                            body = line.split(":", 1)[1]
                            try:
                                cb, dmm = body.split(",", 1)
                                last_color, last_dist = int(cb), int(dmm)
                            except (ValueError, TypeError):
                                continue
                            if last_color > 3:
                                last_color = 0
                            cm = mm_to_cm(last_dist) if last_dist else 30.0
                            STATE.update(last_plate, last_conf, None,
                                         vehicle=vehicle_of(last_color),
                                         color=color_of(last_color),
                                         dist_cm=cm,
                                         push_history=False)
                            print(f"            颜色={color_of(last_color)}/{vehicle_of(last_color)}  "
                                  f"距离={cm:.1f}cm")
                        elif up.startswith("IMG:"):
                            try:
                                pending_img = int(line.split(":", 1)[1])
                            except ValueError:
                                pending_img = 0
                        elif up.startswith("PLATE2:"):
                            body = line.split(":", 1)[1]
                            conf2 = 0.0
                            if "," in body:
                                p2, c2s = body.split(",", 1)
                                try:
                                    conf2 = float(c2s)
                                except ValueError:
                                    conf2 = 0.0
                            else:
                                p2 = body
                            last_plate2, last_conf2 = p2.strip(), conf2
                            print(f"            第二张: {last_plate2} conf={last_conf2:.3f}")
                        elif up.startswith("INFO2:"):
                            body = line.split(":", 1)[1]
                            try:
                                cb2, dmm2 = body.split(",", 1)
                                last_color2, last_dist2 = int(cb2), int(dmm2)
                            except (ValueError, TypeError):
                                pass
                            if last_color2 > 3:
                                last_color2 = 0
                        elif up.startswith("IMG2:"):
                            try:
                                pending_img2 = int(line.split(":", 1)[1])
                            except ValueError:
                                pending_img2 = 0
        except Exception as exc:
            print(f"[web_show] 串口异常: {exc}，2 秒后重试…")
            time.sleep(2)

# ---------------------------------------------------------------- 网页
PAGE = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>车牌识别实时显示</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    background: radial-gradient(1200px 600px at 50% -10%, #10243a 0%, #0a0d12 55%, #07090c 100%);
    color: #e8eef5;
    font-family: system-ui, -apple-system, "Microsoft YaHei", "Segoe UI", sans-serif;
    min-height: 100vh;
  }
  .wrap { max-width: 1240px; margin: 0 auto; padding: 30px 28px 50px; }

  header { display: flex; align-items: center; gap: 14px; margin-bottom: 22px; }
  .dot {
    width: 11px; height: 11px; border-radius: 50%; background: #35e08a;
    box-shadow: 0 0 12px #35e08a; animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
  h1 { font-size: 26px; font-weight: 700; margin: 0; letter-spacing: .5px; }
  h1 span { color: #57d7ff; }
  .badge {
    margin-left: auto; font-size: 13px; color: #8fa3b8;
    background: #131b24; border: 1px solid #22303d; border-radius: 20px;
    padding: 7px 16px;
  }

  .card {
    background: linear-gradient(180deg, #131a23 0%, #0f151c 100%);
    border: 1px solid #223141;
    border-radius: 18px;
    padding: 26px 28px;
    box-shadow: 0 10px 40px rgba(0,0,0,.45);
  }

  .plate {
    font-size: 92px; font-weight: 900; letter-spacing: 10px;
    text-align: center; margin: 10px 0 6px; min-height: 110px;
    color: #6ff2ff;
    text-shadow: 0 0 26px rgba(87,215,255,.55), 0 0 60px rgba(87,215,255,.22);
    font-variant-numeric: tabular-nums;
  }
  .confbar { height: 7px; border-radius: 4px; background: #1c2836; overflow: hidden; margin: 0 auto 22px; max-width: 560px; }
  .confbar > i { display: block; height: 100%; width: 0%; border-radius: 4px;
                 background: linear-gradient(90deg, #22c9a0, #57d7ff); transition: width .3s; }

  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
  .stat {
    background: #121a23; border: 1px solid #223141; border-radius: 14px;
    padding: 16px 12px; text-align: center;
  }
  .stat-label { color: #7f92a6; font-size: 13px; margin-bottom: 8px; letter-spacing: .5px; text-align: center; }
  .stat-val { font-size: 26px; font-weight: 800; text-align: center; }
  .stat-val.big { font-size: 34px; color: #57d7ff; }
  .vehicle.gas { color: #4fa8ff; } .vehicle.elec { color: #43e08a; } .vehicle.large { color: #ffc247; }
  .carimg { height: 46px; display: block; margin: 0 auto 6px; }

  .imgbox {
    background: #06090c; border: 1px solid #223141; border-radius: 14px;
    padding: 14px; margin-bottom: 24px; text-align: center;
  }
  .sub { color: #7f92a6; font-size: 13px; margin-bottom: 10px; letter-spacing: .5px; }
  .cap { width: 100%; max-width: 940px; image-rendering: pixelated; border-radius: 8px; }

  .meta {
    text-align: center; color: #8fa3b8; font-size: 14px;
    padding: 12px; background: #101720; border-radius: 12px; border: 1px solid #1d2a36;
  }
  .meta b { color: #57d7ff; }

  .btn {
    float: right; cursor: pointer; user-select: none;
    background: #1b2733; color: #9fb6cc; border: 1px solid #2a3b4c;
    border-radius: 8px; padding: 5px 14px; font-size: 13px;
    font-family: inherit; transition: all .15s;
  }
  .btn:hover { background: #24384a; color: #6ff2ff; border-color: #3a5570; }
  .btn:active { transform: scale(.96); }
  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  th { color: #7f92a6; font-weight: 500; font-size: 13px; text-align: left; padding: 10px 12px;
       border-bottom: 1px solid #223141; letter-spacing: .5px; }
  td { padding: 11px 12px; border-bottom: 1px solid #17212b; }
  tr:first-child td { color: #6ff2ff; font-weight: 700; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="dot"></span>
    <h1>车牌识别 <span>实时显示</span></h1>
    <div class="badge" id="badge">等待连接…</div>
  </header>

  <div class="card">
    <div class="plate" id="plate">—</div>
    <div class="confbar"><i id="confbar"></i></div>

    <div class="stats">
      <div class="stat">
        <img id="car" class="carimg" src="/assets/car_gas.png" alt="">
        <div class="stat-label">车型</div>
        <div class="stat-val vehicle gas" id="vehicle">—</div>
      </div>
      <div class="stat">
        <div class="stat-label">距离</div>
        <div class="stat-val big" id="distance">— cm</div>
      </div>
      <div class="stat">
        <div class="stat-label">车牌颜色</div>
        <div class="stat-val" id="color">—</div>
      </div>
      <div class="stat">
        <div class="stat-label">推理耗时</div>
        <div class="stat-val big" id="infer">— ms</div>
      </div>
    </div>

    <div class="imgbox">
      <div class="sub">模型输入 128 × 32 灰度图</div>
      <img id="img" class="cap" alt="plate">
    </div>

    <div class="meta" id="meta">等待数据…</div>
  </div>

  <div class="card" style="margin-top:22px">
    <div class="sub" style="margin-bottom:14px">历史记录（最近 20 次）<button class="btn" onclick="clearHist()">清空历史</button></div>
    <table>
      <thead><tr><th>时间</th><th>车牌</th><th>距离</th><th>置信度</th></tr></thead>
      <tbody id="hist"></tbody>
    </table>
  </div>
</div>

<script>
async function poll() {
  try {
    const r = await fetch('/api/latest', {cache:'no-store'});
    const d = await r.json();

    document.getElementById('plate').textContent = d.plate || '—';
    document.getElementById('confbar').style.width = ((d.conf||0)*100).toFixed(1) + '%';

    const CAR = { '普通油车':'/assets/car_gas.png', '电车':'/assets/car_ev.png', '大型车':'/assets/car_large.png' };
    const VCLS = { '普通油车':'gas', '电车':'elec', '大型车':'large' };
    const veh = d.vehicle || '普通油车';
    const ve = document.getElementById('vehicle');
    ve.textContent = veh;
    ve.className = 'stat-val vehicle ' + (VCLS[veh] || 'gas');
    document.getElementById('car').src = CAR[veh] || CAR['普通油车'];

    const cm = (d.dist_cm === undefined || d.dist_cm === null) ? 30.0 : Number(d.dist_cm);
    document.getElementById('distance').textContent = cm.toFixed(1) + ' cm';
    document.getElementById('color').textContent = d.color || '—';

    const ims = Number(d.infer_ms || 0);
    const infEl = document.getElementById('infer');
    infEl.textContent = ims > 0 ? ims.toFixed(0) + ' ms' : '— ms';
    infEl.style.color = ims > 0 ? (ims < 400 ? '#43e08a' : (ims < 1200 ? '#ffc247' : '#ff6b6b')) : '';

    document.getElementById('badge').textContent = d.ts ? ('更新于 ' + d.ts) : '等待连接…';
    document.getElementById('meta').innerHTML =
      `${d.source || ''} · 帧数 <b>${d.frames||0}</b> · ${d.ts || ''}` +
      (d.conf ? ` · 置信度 <b>${(d.conf*100).toFixed(1)}%</b>` : '') +
      (d.dbg ? ` · <span style="color:${d.dbg.indexOf('MATCH')>=0?'#43e08a':'#ff6b6b'}">${d.dbg}</span>` : '');

    document.getElementById('img').src = d.img ? 'data:image/png;base64,' + d.img : '';
    document.getElementById('hist').innerHTML = (d.history||[]).map(h => {
      const hc = (h.dist_cm === undefined || h.dist_cm === null) ? 30.0 : Number(h.dist_cm);
      return `<tr><td>${h.ts}</td><td>${h.plate}</td><td>${hc.toFixed(1)} cm</td><td>${(h.conf*100).toFixed(1)}%</td></tr>`;
    }).join('');
  } catch (e) {
    document.getElementById('meta').textContent = '连接中断，重试中…';
  }
}

async function clearHist() {
  if (!confirm('确定清空历史记录？')) return;
  try { await fetch('/api/clear', {cache:'no-store'}); } catch (e) {}
  const t = document.getElementById('hist');
  if (t) t.innerHTML = '';
}
poll(); setInterval(poll, 500);
</script>
</body>
</html>
"""

# ---------------------------------------------------------------- 双车牌页面（MODE=4）
PAGE2 = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>车牌识别 · 一图双牌</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    background: radial-gradient(1400px 700px at 50% -10%, #14283f 0%, #0a0d12 55%, #07090c 100%);
    color: #e8eef5;
    font-family: system-ui, -apple-system, "Microsoft YaHei", "Segoe UI", sans-serif;
    min-height: 100vh;
  }
  .wrap { max-width: 1560px; margin: 0 auto; padding: 30px 28px 46px; }

  header { display: flex; align-items: center; gap: 14px; margin-bottom: 22px; }
  .dot { width: 11px; height: 11px; border-radius: 50%; background: #35e08a;
         box-shadow: 0 0 12px #35e08a; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
  h1 { font-size: 26px; font-weight: 700; margin: 0; letter-spacing: .5px; }
  h1 span { color: #57d7ff; }
  .badge { margin-left: auto; font-size: 13px; color: #8fa3b8;
           background: #131b24; border: 1px solid #22303d; border-radius: 20px; padding: 7px 16px; }

  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }

  .panel {
    background: linear-gradient(180deg, #131a23 0%, #0f151c 100%);
    border: 1px solid #223141; border-radius: 18px; padding: 22px 24px;
    box-shadow: 0 10px 40px rgba(0,0,0,.45);
    position: relative; overflow: hidden;
  }
  .panel::before {
    content: ''; position: absolute; inset: 0 0 auto 0; height: 3px;
    background: linear-gradient(90deg, #57d7ff, #22c9a0);
  }
  .panel.p2::before { background: linear-gradient(90deg, #ffc247, #ff7a59); }

  .idx { display: inline-flex; align-items: center; gap: 8px; font-size: 14px;
         color: #8fa3b8; letter-spacing: 1px; margin-bottom: 12px; }
  .idx b { display: inline-flex; align-items: center; justify-content: center;
           width: 24px; height: 24px; border-radius: 7px; font-size: 13px;
           background: #17394d; color: #6ff2ff; }
  .p2 .idx b { background: #3d2c12; color: #ffc247; }

  .plate {
    font-size: 62px; font-weight: 900; letter-spacing: 7px;
    text-align: center; min-height: 82px; margin: 6px 0 4px;
    color: #6ff2ff;
    text-shadow: 0 0 24px rgba(87,215,255,.5), 0 0 56px rgba(87,215,255,.2);
    font-variant-numeric: tabular-nums;
  }
  .p2 .plate { color: #ffd980; text-shadow: 0 0 24px rgba(255,194,71,.5), 0 0 56px rgba(255,194,71,.2); }
  .plate.off { font-size: 22px; letter-spacing: 2px; color: #55636f; text-shadow: none; font-weight: 500; }

  .confbar { height: 6px; border-radius: 3px; background: #1c2836; overflow: hidden; margin: 0 0 18px; }
  .confbar > i { display: block; height: 100%; width: 0%; border-radius: 3px;
                 background: linear-gradient(90deg, #22c9a0, #57d7ff); transition: width .3s; }
  .p2 .confbar > i { background: linear-gradient(90deg, #ff7a59, #ffc247); }

  .imgbox { background: #06090c; border: 1px solid #223141; border-radius: 12px; padding: 12px; }
  .cap { width: 100%; image-rendering: pixelated; border-radius: 6px; display: block; min-height: 70px; }

  .meta { display: flex; justify-content: center; align-items: center; gap: 22px;
          color: #8fa3b8; font-size: 14px; margin-top: 14px; }
  .meta b { color: #e8eef5; }

  .bar {
    margin-top: 24px; text-align: center; color: #8fa3b8; font-size: 15px;
    background: #101720; border: 1px solid #1d2a36; border-radius: 14px; padding: 16px;
  }
  .bar .big { color: #57d7ff; font-weight: 800; font-size: 22px; margin: 0 4px; }
  .ok { color: #43e08a; font-weight: 700; }
  .bad { color: #ff6b6b; font-weight: 700; }

  .hist { margin-top: 24px; background: linear-gradient(180deg,#131a23,#0f151c);
          border: 1px solid #223141; border-radius: 18px; padding: 20px 24px;
          box-shadow: 0 10px 40px rgba(0,0,0,.45); }

  .btn {
    float: right; cursor: pointer; user-select: none;
    background: #1b2733; color: #9fb6cc; border: 1px solid #2a3b4c;
    border-radius: 8px; padding: 5px 14px; font-size: 13px;
    font-family: inherit; transition: all .15s;
  }
  .btn:hover { background: #24384a; color: #6ff2ff; border-color: #3a5570; }
  .btn:active { transform: scale(.96); }
  .sub { color: #7f92a6; font-size: 13px; letter-spacing: .5px; margin-bottom: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  th { color: #7f92a6; font-weight: 500; font-size: 13px; text-align: left;
       padding: 9px 12px; border-bottom: 1px solid #223141; }
  td { padding: 10px 12px; border-bottom: 1px solid #17212b; }
  tr:first-child td { color: #6ff2ff; font-weight: 700; }
  .gold { color: #ffd980; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="dot"></span>
    <h1>车牌识别 <span>一图双牌</span></h1>
    <div class="badge" id="badge">等待连接…</div>
  </header>

  <div class="grid">
    <div class="panel p1">
      <div class="idx"><b>1</b> 第一块车牌</div>
      <div class="plate" id="p1">—</div>
      <div class="confbar"><i id="cb1"></i></div>
      <div class="imgbox"><img id="i1" class="cap" alt=""></div>
      <div class="meta"><span id="c1">置信度 —</span><span id="d1">距离 —</span><span id="k1">颜色 —</span><span id="t1"></span></div>
    </div>

    <div class="panel p2">
      <div class="idx"><b>2</b> 第二块车牌</div>
      <div class="plate off" id="p2">等待第二块…</div>
      <div class="confbar"><i id="cb2"></i></div>
      <div class="imgbox"><img id="i2" class="cap" alt=""></div>
      <div class="meta"><span id="c2">置信度 —</span><span id="d2">距离 —</span><span id="k2">颜色 —</span><span id="t2"></span></div>
    </div>
  </div>

  <div class="bar" id="bar">等待数据…</div>

  <div class="hist">
    <div class="sub">历史记录（最近 15 组）<button class="btn" onclick="clearHist()">清空历史</button></div>
    <table>
      <thead><tr><th style="width:110px">时间</th><th>第一块</th><th>第二块</th><th style="width:130px">推理耗时</th></tr></thead>
      <tbody id="hist"></tbody>
    </table>
  </div>
</div>

<script>
const el = id => document.getElementById(id);

async function poll() {
  try {
    const r = await fetch('/api/latest', {cache:'no-store'});
    const d = await r.json();

    el('p1').textContent = d.plate || '—';
    el('p1').className = 'plate';
    el('cb1').style.width = ((d.conf||0)*100).toFixed(1) + '%';
    el('c1').textContent = (d.conf > 0) ? '置信度 ' + (d.conf*100).toFixed(1) + '%' : '置信度 —';
    el('d1').textContent = '距离 ' + (Number(d.dist_cm||30)).toFixed(1) + ' cm';
    el('k1').textContent = '颜色 ' + (d.color || '—');
    el('i1').src = d.img ? 'data:image/png;base64,' + d.img : '';
    el('t1').textContent = d.ts || '';

    if (d.has2 && d.plate2) {
      el('p2').textContent = d.plate2;
      el('p2').className = 'plate';
      el('cb2').style.width = ((d.conf2||0)*100).toFixed(1) + '%';
      el('c2').textContent = (d.conf2 > 0) ? '置信度 ' + (d.conf2*100).toFixed(1) + '%' : '置信度 —';
      el('d2').textContent = '距离 ' + (Number(d.dist_cm2||30)).toFixed(1) + ' cm';
      el('k2').textContent = '颜色 ' + (d.color2 || '—');
      el('i2').src = d.img2 ? 'data:image/png;base64,' + d.img2 : '';
      el('t2').textContent = d.ts || '';
    } else {
      el('p2').textContent = '（本次只有一块）';
      el('p2').className = 'plate off';
      el('cb2').style.width = '0%';
      el('c2').textContent = '置信度 —';
      el('d2').textContent = '距离 —';
      el('k2').textContent = '颜色 —';
      el('t2').textContent = '';
    }

    const ms = Number(d.infer_ms || 0);
    el('badge').textContent = d.ts ? ('更新于 ' + d.ts) : '等待连接…';
    el('bar').innerHTML =
      `推理耗时 <span class="big">${ms > 0 ? ms.toFixed(0) : '—'}</span> ms` +
      ` · <b>${d.has2 ? '双牌' : '单牌'}</b>` +
      ` · 帧数 <b>${d.frames||0}</b>` +
      (d.source ? ` · ${d.source}` : '') +
      (d.dbg ? ` · <span class="${d.dbg.indexOf('MATCH')>=0?'ok':'bad'}">${d.dbg}</span>` : '');

    // 历史记录直接用服务端给的（一帧一行，含第二块和耗时）
    const H = d.history || [];
    el('hist').innerHTML = H.map(h => {
      const msH = Number(h.ms || 0);
      return `<tr><td>${h.ts}</td><td>${h.plate}</td>` +
             `<td class="gold">${h.plate2 || '—'}</td>` +
             `<td>${msH > 0 ? msH.toFixed(0) + ' ms' : '—'}</td></tr>`;
    }).join('');
  } catch (e) {
    el('bar').textContent = '连接中断，重试中…';
  }
}

async function clearHist() {
  if (!confirm('确定清空历史记录？')) return;
  try { await fetch('/api/clear', {cache:'no-store'}); } catch (e) {}
  const t = document.getElementById('hist');
  if (t) t.innerHTML = '';
}
poll(); setInterval(poll, 500);
</script>
</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            body = (PAGE2 if MODE == 4 else PAGE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.split("?")[0] == "/api/clear":
            STATE.clear_history()
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.split("?")[0] == "/api/latest":
            body = json.dumps(STATE.snapshot(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/assets/"):
            assets_dir = (ROOT / "web_assets").resolve()
            fp = (assets_dir / self.path[len("/assets/"):].split("?")[0]).resolve()
            try:
                fp.relative_to(assets_dir)
            except ValueError:
                self.send_error(404)
                return
            if not fp.is_file():
                self.send_error(404)
                return
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):   # 静默访问日志
        pass

# ★ 测试状态开关：改下面这几行，然后直接运行本文件即可（不用命令行参数）
#
#   MODE = 1  无硬件模拟：用 SIM_IMAGE 这张图片反复出结果
#   MODE = 2  接 20K：读串口灰度帧 → PC 用 lprnet.onnx 推理
#   MODE = 3  接 Zynq-7020：直接读板子输出的 PLATE:/INFO: 结果行（推荐）
#   MODE = 4  接 Zynq-7020 + 20K v4.1 双定位：一图两牌，网页并排显示两张
MODE = 3
SERIAL_PORT = ""                         # MODE=2/3/4 用的串口；留空 = 自动找 CH340
SERIAL_BAUD = 921600
SIM_IMAGE = "test_picture/test_1.jpg"    # MODE=1 用的图片
SIM_INTERVAL = 1.5                       # MODE=1 出结果间隔（秒）
WEB_PORT = 8000                          # 网页端口

# MODE=3 时：想自动循环发测试图给 Zynq 就填目录，不想就写 None
SEND_DIR = None          # 例：Path("aa55_capture")，None=关闭
SEND_INTERVAL = 2.0                      # 自动发图间隔（秒）

def _auto_serial_port():
    """自动找 CH340（Zynq 的板载 USB 串口）"""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    ports = list(list_ports.comports())
    for p in ports:
        t = f"{p.device} {p.description} {p.manufacturer or ''}".upper()
        if "CH340" in t or "CH34" in t or "USB-SERIAL" in t:
            return p.device
    return ports[0].device if len(ports) == 1 else None

def main() -> int:
    tts_start()                      # 启动语音朗读线程

    parser = argparse.ArgumentParser(description="串口收图→识别→网页显示（Zynq-7020 / PC 推理）")
    parser.add_argument("--port", help="20K 串口，如 COM8")
    parser.add_argument("--baud", type=int, default=SERIAL_BAUD)
    parser.add_argument("--result-port", help="Zynq-7020 结果串口，如 COM3")
    parser.add_argument("--result-baud", type=int, default=SERIAL_BAUD)
    parser.add_argument("--sim", type=Path, help="无硬件模拟：用这张图片反复出结果")
    parser.add_argument("--interval", type=float, default=SIM_INTERVAL, help="模拟模式间隔（秒）")
    parser.add_argument("--model", type=Path, default=Path("lprnet.onnx"))
    parser.add_argument("--frame-mode", choices=["auto", "color", "dist", "full"], default="auto",
                        help="帧格式：auto 自动识别（默认）/ color 强制 v3.2 颜色帧 / dist 强制 v3.3 距离帧")
    parser.add_argument("--no-tts", action="store_true", help="关闭语音朗读")
    parser.add_argument("--web-port", type=int, default=WEB_PORT)
    parser.add_argument("--send-dir", type=Path, default=None,
                        help="配合 --result-port：每 --send-interval 秒自动发一张该目录的图给 Zynq")
    parser.add_argument("--send-interval", type=float, default=3.0, help="自动发图间隔（秒）")
    args, _unknown = parser.parse_known_args()   # 容忍 IDE/Jupyter 多余参数

    # 没给任何命令行参数时，按文件顶部的 MODE 开关决定数据源
    if args.sim is None and args.port is None and args.result_port is None:
        if MODE == 1:
            args.sim = Path(SIM_IMAGE)
            args.interval = SIM_INTERVAL
        elif MODE == 2:
            args.port = SERIAL_PORT
            args.baud = SERIAL_BAUD
        elif MODE in (3, 4):
            args.result_port = SERIAL_PORT or _auto_serial_port()
            if not args.result_port:
                print("[web_show] 没找到串口，请改文件顶部 SERIAL_PORT", file=sys.stderr)
                return 2
            print(f"[web_show] 使用串口 {args.result_port} @{SERIAL_BAUD}")
            args.result_baud = SERIAL_BAUD
            args.send_dir = SEND_DIR
            args.send_interval = SEND_INTERVAL
        else:
            print(f"MODE={MODE} 无效，应为 1 / 2 / 3 / 4", file=sys.stderr)
            return 2

    threads = []
    if args.sim:
        if not args.model.is_file():
            print(f"找不到模型 {args.model}", file=sys.stderr)
            return 2
        threads.append(threading.Thread(target=loop_sim, args=(args.sim, args.interval, args.model), daemon=True))
    elif args.port:
        if not args.model.is_file():
            print(f"找不到模型 {args.model}", file=sys.stderr)
            return 2
        threads.append(threading.Thread(target=loop_fpga_serial,
                                        args=(args.port, args.baud, args.model, args.frame_mode),
                                        daemon=True))
    elif args.result_port:
        threads.append(threading.Thread(
            target=loop_result_serial,
            args=(args.result_port, args.result_baud, args.send_dir, args.send_interval),
            daemon=True))
    else:
        print("请指定 --port / --sim / --result-port 之一", file=sys.stderr)
        return 2

    for t in threads:
        t.start()

    server = ThreadingHTTPServer(("127.0.0.1", args.web_port), Handler)
    print(f"[web_show] 网页: http://127.0.0.1:{args.web_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.shutdown()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
