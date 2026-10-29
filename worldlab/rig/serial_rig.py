"""Hardware rig over a serial line (Arduino / ESP32 running firmware/worldlab_rig).

Protocol, 115200 baud, one ASCII line per message:
  rig -> host  D,<ms>,<T_obj C>,<T_amb C>,<fan %>,<heater 0|1>,<fan mW or -1>,<flags>
  host -> rig  F <0-100>     set fan duty
               H <0|1>       heater off / on
               P             heartbeat (the rig goes safe if it hears nothing for 10 s)
               S             safe state now (heater off, fan 100%)
               R             clear a latched over-temperature trip
The firmware enforces its own limits independently of this program.
"""
from __future__ import annotations

import threading
import time

from .base import Rig, Sample, Capabilities, fan_power_model


class SerialRig(Rig):
    def __init__(self, port: str, baud: int = 115200, heater_w: float = 10.0, camera_index: int = -1):
        try:
            import serial  # pyserial
        except ImportError as e:
            raise RuntimeError("the hardware rig needs pyserial: pip install pyserial") from e
        if not port:
            raise RuntimeError("give the serial port, e.g. --port COM3 or --port /dev/ttyACM0")
        self.ser = serial.Serial(port, baud, timeout=0.2)
        time.sleep(2.0)  # most boards reset when the port opens
        self.t0 = time.monotonic()
        self.heater_w = heater_w
        self._lock = threading.Lock()
        self._buf: list[Sample] = []
        self._all: list[Sample] = []
        self._last_hb = 0.0
        self._stop = False
        self._has_meter = False
        self.flags = ""
        self.cam = None
        if camera_index >= 0:
            try:
                import cv2
                self.cv2 = cv2
                self.cam = cv2.VideoCapture(camera_index)
                if not self.cam.isOpened():
                    self.cam = None
            except ImportError:
                self.cam = None
        self.caps = Capabilities(simulated=False, has_heater=True, heater_w=heater_w,
                                 has_camera=self.cam is not None, has_power_meter=False, sample_period_s=1.0)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._send("R")
        self.set_heater(False)
        self.set_fan(0.0)

    def _send(self, line: str):
        with self._lock:
            self.ser.write((line + "\n").encode())
            self._last_hb = time.monotonic()

    def _read_loop(self):
        while not self._stop:
            try:
                raw = self.ser.readline().decode(errors="replace").strip()
            except Exception:
                time.sleep(0.2)
                continue
            if not raw.startswith("D,"):
                continue
            parts = raw.split(",")
            try:
                T_obj, T_amb = float(parts[2]), float(parts[3])
                duty = float(parts[4]) / 100.0
                heat = self.heater_w if parts[5].strip() == "1" else 0.0
                mw = float(parts[6])
                self.flags = parts[7] if len(parts) > 7 else ""
            except (IndexError, ValueError):
                continue
            if mw >= 0:
                self._has_meter = True
            p = mw / 1000.0 if mw >= 0 else fan_power_model(duty)
            s = Sample(t=round(time.monotonic() - self.t0, 3), T_obj=T_obj, T_amb=T_amb, fan_duty=duty,
                       heater_w=heat, fan_power_w=p)
            with self._lock:
                self._buf.append(s)

    # ------------------------------------------------------------------ Rig
    def now(self) -> float:
        return time.monotonic() - self.t0

    def set_fan(self, duty: float) -> None:
        self._send(f"F {int(round(min(max(duty, 0.0), 1.0) * 100))}")

    def set_heater(self, on: bool) -> None:
        self._send(f"H {1 if on else 0}")

    def advance(self, seconds: float) -> list[Sample]:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if time.monotonic() - self._last_hb > 2.0:
                self._send("P")
            time.sleep(min(0.25, max(0.0, end - time.monotonic())))
        return self.drain()

    def drain(self) -> list[Sample]:
        if time.monotonic() - self._last_hb > 2.0:
            self._send("P")
        with self._lock:
            out, self._buf = self._buf, []
        return out

    def safe_state(self) -> None:
        self._send("S")

    def capture_frame(self) -> bytes | None:
        if self.cam is None:
            return None
        ok, frame = self.cam.read()
        if not ok:
            return None
        ok, jpg = self.cv2.imencode(".jpg", frame, [int(self.cv2.IMWRITE_JPEG_QUALITY), 85])
        return jpg.tobytes() if ok else None

    def frame_mime(self) -> str:
        return "image/jpeg"

    def close(self) -> None:
        try:
            self.safe_state()
        finally:
            self._stop = True
            self.ser.close()
            if self.cam is not None:
                self.cam.release()
