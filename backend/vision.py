import os
import threading
import time

import cv2
import numpy as np

from config import YOLO_MODEL, YOLO_CONF, YOLO_IMGSZ

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", YOLO_MODEL)

_ALERT_CLASSES = {"person", "bicycle", "car", "motorcycle", "bus", "truck",
                  "cat", "dog"}
_LIGHT_CLASS = "traffic light"


_BANDS = (
    ("red",   ((0, 110, 110), (10, 255, 255)), ((170, 110, 110), (180, 255, 255))),
    ("amber", ((15, 110, 130), (35, 255, 255)), None),
    ("green", ((40, 80, 90), (90, 255, 255)), None),
)
_LIGHT_MIN_FRAC = 0.02


def _light_counts(roi):
    if roi is None or roi.size == 0:
        return {}, 0
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    out = {}
    for name, a, b in _BANDS:
        mask = cv2.inRange(hsv, a[0], a[1])
        if b is not None:
            mask = mask | cv2.inRange(hsv, b[0], b[1])
        out[name] = int(cv2.countNonZero(mask))
    return out, int(roi.shape[0] * roi.shape[1])


def _classify_light(roi):
    counts, area = _light_counts(roi)
    if not area:
        return "none"
    r, g = counts.get("red", 0), counts.get("green", 0)
    if max(r, g) < _LIGHT_MIN_FRAC * area:
        return "none"
    return "red" if r >= g else "green"


_MIN_SIDE = 48
_BRIGHT_PCT = 88


def _bright_vote(roi):
    h, w = roi.shape[:2]
    if h < 3 or w < 2:
        return None
    if min(h, w) < _MIN_SIDE:
        s = _MIN_SIDE / float(min(h, w))
        roi = cv2.resize(roi, (max(2, int(w * s)), max(3, int(h * s))),
                         interpolation=cv2.INTER_CUBIC)
        h, w = roi.shape[:2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    V = hsv[:, :, 2]
    thr = float(np.percentile(V, _BRIGHT_PCT))
    if thr < 45 or float(np.percentile(V, 95) - np.percentile(V, 20)) < 22:
        return None

    mask = (V >= thr).astype(np.uint8)
    cnt, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    if cnt < 2:
        return None
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    sel = labels == big
    if int(sel.sum()) < 6:
        return None
    ys, xs = np.where(sel)
    hue = hsv[:, :, 0][ys, xs].astype(np.float32)
    hshift = np.where(hue > 135, hue - 180.0, hue)
    hm = float(np.median(hshift))
    band = ("red" if hm <= 12 else "amber" if hm <= 34 else
            "green" if hm <= 95 else "red")
    pos = float(np.median(ys)) / max(1.0, h - 1.0)
    by_pos = "red" if pos < 0.38 else "amber" if pos < 0.66 else "green"
    adjacent = {("red", "amber"), ("amber", "red"),
                ("amber", "green"), ("green", "amber")}
    agreed = band == by_pos
    if not agreed and (band, by_pos) in adjacent:
        band = by_pos
    return {"colour": band, "hue": round(hm, 1), "pos": round(pos, 2),
            "agreed": agreed, "n": int(len(hue))}


def classify_light_full(roi):
    counts, area = _light_counts(roi)
    if not area:
        return {"colour": "none", "counts": {}, "frac": 0.0, "margin": 0.0,
                "method": "none"}
    order = sorted(counts.items(), key=lambda kv: -kv[1])
    top, n = order[0]
    runner = order[1][1] if len(order) > 1 else 0
    if n >= _LIGHT_MIN_FRAC * area:
        return {"colour": top, "counts": counts, "frac": round(n / float(area), 4),
                "margin": round((n - runner) / float(n), 3), "method": "strict"}

    v = _bright_vote(roi)
    if v is None:
        return {"colour": "none", "counts": counts, "frac": n / float(area),
                "margin": 0.0, "method": "none"}
    return {"colour": v["colour"], "counts": counts,
            "frac": round(n / float(area), 4),
            "margin": 0.55 if v["agreed"] else 0.3,
            "method": "bright", "hue": v["hue"], "pos": v["pos"],
            "agreed": v["agreed"]}


class VisionProcessor:
    def __init__(self, enable_traffic=True, enable_objects=True,
                 conf=YOLO_CONF, imgsz=YOLO_IMGSZ):
        self.enable_traffic = enable_traffic
        self.enable_objects = enable_objects
        self.conf = conf
        self.imgsz = imgsz
        self._model = None
        self._names = {}
        self._last_objects = []
        self._latest = None
        self._lock = threading.Lock()
        self._stop = False
        self._worker = threading.Thread(target=self._detect_loop, daemon=True)
        self._worker.start()

    def _load_model(self):
        try:
            import torch
            torch.set_num_threads(2)
            from ultralytics import YOLO
            self._model = YOLO(_MODEL_PATH)
            self._names = self._model.names
            try:
                self._model.predict(np.zeros((self.imgsz, self.imgsz, 3), np.uint8),
                                    imgsz=self.imgsz, verbose=False)
            except Exception:
                pass
            print("[vision] YOLO loaded + warmed: %s" % _MODEL_PATH)
        except Exception as e:
            self._model = "FAILED"
            print("[vision] YOLO load failed (%s); object detection off" % e)

    def _detect_loop(self):
        while not self._stop:
            if not self.enable_objects:
                time.sleep(0.2)
                continue
            if self._model is None:
                self._load_model()
            if self._model == "FAILED":
                time.sleep(2.0)
                continue
            frame = self._latest
            if frame is None:
                time.sleep(0.05)
                continue
            try:
                res = self._model.predict(frame, imgsz=self.imgsz, conf=self.conf,
                                          verbose=False)[0]
                objs = []
                for b in res.boxes:
                    cls = int(b.cls[0])
                    label = self._names[cls] if cls in self._names else str(cls)
                    x1, y1, x2, y2 = [int(v) for v in b.xyxy[0].tolist()]
                    objs.append({"label": label, "conf": round(float(b.conf[0]), 2),
                                 "box": [x1, y1, x2 - x1, y2 - y1],
                                 "alert": label in _ALERT_CLASSES})
                with self._lock:
                    self._last_objects = objs
            except Exception as e:
                print("[vision] detect error: %s" % e)
            time.sleep(0.1)

    def clear(self):
        self._latest = None
        with self._lock:
            self._last_objects = []

    def set_options(self, enable_traffic=None, enable_objects=None, conf=None):
        if enable_traffic is not None:
            self.enable_traffic = bool(enable_traffic)
        if enable_objects is not None:
            self.enable_objects = bool(enable_objects)
        if conf is not None:
            try:
                self.conf = max(0.05, min(0.95, float(conf)))
            except (TypeError, ValueError):
                pass

    def process(self, frame):
        self._latest = frame.copy()
        with self._lock:
            objects = list(self._last_objects)
        objs_on = self.enable_objects and self._model not in (None, "FAILED")
        status = ("off" if not self.enable_objects else
                  "loading" if self._model is None else
                  "failed" if self._model == "FAILED" else "ready")
        results = {"traffic_light": "none", "objects": objects,
                   "objects_enabled": objs_on, "detector_status": status,
                   "traffic_enabled": bool(self.enable_traffic),
                   "model": YOLO_MODEL,
                   "conf": round(float(self.conf), 2)}

        light = "none"
        if self.enable_traffic:
            lights = [o for o in objects if o["label"] == _LIGHT_CLASS]
            if lights:
                lights.sort(key=lambda o: o["box"][2] * o["box"][3], reverse=True)
                x, y, w, h = lights[0]["box"]
                x, y = max(0, x), max(0, y)
                light = _classify_light(frame[y:y + h, x:x + w])
            elif not objs_on:
                light = _classify_light(frame)
        results["traffic_light"] = light

        for o in objects:
            x, y, w, h = o["box"]
            if o["label"] == _LIGHT_CLASS:
                col = ((0, 0, 255) if light == "red" else
                       (0, 220, 0) if light == "green" else (0, 200, 255))
                tag = "light %s" % light if light != "none" else "traffic light"
            elif o["alert"]:
                col, tag = (0, 165, 255), "%s %s" % (o["label"], o["conf"])
            else:
                col, tag = (200, 200, 0), "%s %s" % (o["label"], o["conf"])
            cv2.rectangle(frame, (x, y), (x + w, y + h), col, 2)
            cv2.putText(frame, tag, (x, max(15, y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)

        if light != "none":
            cv2.putText(frame, "LIGHT: %s" % light.upper(), (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 0, 255) if light == "red" else (0, 220, 0), 2, cv2.LINE_AA)

        if status == "loading":
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 26), (60, 25, 40), -1)
            cv2.putText(frame, "Loading object detector (YOLO)...", (8, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 210, 255), 1, cv2.LINE_AA)

        return frame, results

    def shutdown(self):
        self._stop = True
