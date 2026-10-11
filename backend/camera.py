import os
import threading
import time

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
import cv2
import numpy as np

from config import (CAMERA_INDEX, CAMERA_SCAN_MAX, CAMERA_MIN_WIDTH,
                    CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS)

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except Exception:
    pass

RECONNECT_S = 10.0


def _placeholder(text="NO CAMERA", hint="plug in a USB webcam",
                 w=CAMERA_WIDTH, h=CAMERA_HEIGHT):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (30, 30, 35)
    cv2.putText(img, text, (int(w * 0.18), int(h * 0.5)),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (90, 90, 200), 2, cv2.LINE_AA)
    cv2.putText(img, hint, (int(w * 0.20), int(h * 0.5) + 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 140, 140), 1, cv2.LINE_AA)
    return img


class CameraStreamer:
    def __init__(self, vision=None, settings=None):
        self.vision = vision
        self.settings = settings
        self.results = {}
        self._cap = None
        self._lock = threading.Lock()
        self._jpeg = self._encode(_placeholder())
        self.connected = False
        self.fps = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    @property
    def enabled(self):
        if self.settings is None:
            return True
        try:
            return bool(self.settings["camera"])
        except (KeyError, TypeError):
            return True

    def _encode(self, frame):
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else b""

    def _try_index(self, index):
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        ok, frame = cap.read()
        if ok and frame is not None and frame.shape[1] >= CAMERA_MIN_WIDTH:
            print("[camera] using /dev/video%d (%dx%d)"
                  % (index, frame.shape[1], frame.shape[0]))
            return cap
        cap.release()
        return None

    def _open(self):
        if os.environ.get("SUKI_NO_CAMERA"):
            print("[camera] SUKI_NO_CAMERA is set - not opening any device")
            self._stop.set()
            return None
        order = [CAMERA_INDEX] + [i for i in range(CAMERA_SCAN_MAX) if i != CAMERA_INDEX]
        for i in order:
            cap = self._try_index(i)
            if cap is not None:
                return cap
        return None

    def _release(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None
        self.connected = False
        self.fps = 0.0

    def _run(self):
        last_try = 0.0
        t_prev = time.time()
        was_on = True
        while not self._stop.is_set():
            if not self.enabled:
                if was_on:
                    was_on = False
                    self._release()
                    self.results = {}
                    if self.vision is not None:
                        self.vision.clear()
                    with self._lock:
                        self._jpeg = self._encode(_placeholder(
                            "CAMERA OFF", "switch it on in the Vision tab"))
                    print("[camera] switched off - device released")
                self._stop.wait(0.3)
                continue
            if not was_on:
                was_on = True
                last_try = 0.0
                t_prev = time.time()
                print("[camera] switched on")

            if self._cap is None:
                if time.time() - last_try > RECONNECT_S:
                    last_try = time.time()
                    self._cap = self._open()
                    self.connected = self._cap is not None
                if self._cap is None:
                    with self._lock:
                        self._jpeg = self._encode(_placeholder())
                    time.sleep(0.5)
                    continue

            ok, frame = self._cap.read()
            if not ok:
                self._cap.release()
                self._cap = None
                self.connected = False
                continue

            if self.vision is not None:
                try:
                    frame, self.results = self.vision.process(frame)
                except Exception as e:
                    self.results = {"error": str(e)}

            now = time.time()
            dt = now - t_prev
            t_prev = now
            if dt > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)

            with self._lock:
                self._jpeg = self._encode(frame)
            time.sleep(max(0, 1.0 / CAMERA_FPS - 0.005))

    def latest_jpeg(self) -> bytes:
        with self._lock:
            return self._jpeg

    def mjpeg_generator(self):
        boundary = b"--frame"
        while not self._stop.is_set():
            jpeg = self.latest_jpeg()
            yield (boundary + b"\r\nContent-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                   + jpeg + b"\r\n")
            time.sleep(1.0 / CAMERA_FPS)

    def state(self):
        return {"connected": bool(self.connected), "fps": round(self.fps, 1),
                "enabled": bool(self.enabled)}

    def shutdown(self):
        self._stop.set()
        self._release()
