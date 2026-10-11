import json
import os
import threading
import time
import uuid

import cv2
import numpy as np

from config import (LAB_DIR, LAB_MAX_IMAGES, LAB_MAX_LONG_EDGE, LAB_MAX_UPLOAD_BYTES,
                    LAB_THUMB_EDGE, WALK_COLOURS)
from vision import classify_light_full

_HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(_HERE, "models")


def _is_light(label):
    s = "".join(c for c in str(label).lower() if c.isalnum())
    return "trafficlight" in s or s in ("light", "tl", "signal", "trafficsignal")


_LIGHT_BGR = {"red": (114, 114, 248), "amber": (35, 189, 251), "green": (153, 211, 54)}


def _slug(name):
    keep = "".join(c if c.isalnum() or c in "-_. " else "_" for c in str(name or ""))
    return keep.strip()[:48] or "image"


class Lab:
    def __init__(self, root, write_json):
        self.dir = os.path.join(root, LAB_DIR)
        self.runs_path = os.path.join(root, "lab_runs.json")
        self._write = write_json
        os.makedirs(self.dir, exist_ok=True)
        self.images = []
        self.runs = {}
        self._models = {}
        self._names = {}
        self._lru = []
        self._lock = threading.Lock()
        self._queue = []
        self._busy = None
        self._note = ""
        self._rev = 0
        self._stop = False
        self._load()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def _load(self):
        try:
            with open(self.runs_path) as f:
                raw = json.load(f)
            self.runs = raw.get("runs") or {}
        except (OSError, ValueError):
            self.runs = {}
        for fn in sorted(os.listdir(self.dir)):
            if not fn.endswith(".jpg") or fn.endswith((".thumb.jpg", ".out.jpg")):
                continue
            iid = fn[:-4]
            path = os.path.join(self.dir, fn)
            meta = (self.runs.get(iid) or {}).get("_meta") or {}
            self.images.append({
                "id": iid,
                "name": meta.get("name") or iid,
                "w": meta.get("w") or 0, "h": meta.get("h") or 0,
                "bytes": os.path.getsize(path),
                "when": meta.get("when") or os.path.getmtime(path),
            })
        self.images.sort(key=lambda i: i["when"], reverse=True)
        have = {i["id"] for i in self.images}
        gone = [k for k in self.runs if k not in have]
        for k in gone:
            self.runs.pop(k, None)
        orphans = 0
        try:
            for fn in os.listdir(self.dir):
                if fn.endswith(".out.jpg") and fn.split("__")[0] not in have:
                    os.remove(os.path.join(self.dir, fn))
                    orphans += 1
        except OSError:
            pass
        if gone or orphans:
            print("[lab] dropped %d orphan run record(s) and %d annotated picture(s) "
                  "whose image is gone" % (len(gone), orphans))
            self._save_runs()

    def _save_runs(self):
        try:
            self._write(self.runs_path, {"runs": self.runs})
        except OSError as e:
            print("[lab] could not write %s: %s" % (self.runs_path, e))

    def add(self, data, name=None):
        if not data or len(data) > LAB_MAX_UPLOAD_BYTES:
            return None, "too big (limit %d MB)" % (LAB_MAX_UPLOAD_BYTES // (1 << 20))
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None, "not an image this build of OpenCV can read"
        h, w = img.shape[:2]
        long_edge = max(w, h)
        if long_edge > LAB_MAX_LONG_EDGE:
            s = LAB_MAX_LONG_EDGE / float(long_edge)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
            h, w = img.shape[:2]
        iid = uuid.uuid4().hex[:12]
        cv2.imwrite(os.path.join(self.dir, iid + ".jpg"), img,
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
        ts = max(1, int(LAB_THUMB_EDGE * min(w, h) / float(max(w, h))))
        thumb = cv2.resize(img, (LAB_THUMB_EDGE, ts) if w >= h else (ts, LAB_THUMB_EDGE),
                           interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(self.dir, iid + ".thumb.jpg"), thumb,
                    [cv2.IMWRITE_JPEG_QUALITY, 78])
        rec = {"id": iid, "name": _slug(name), "w": w, "h": h,
               "bytes": os.path.getsize(os.path.join(self.dir, iid + ".jpg")),
               "when": time.time()}
        with self._lock:
            self.images.insert(0, rec)
            self.runs.setdefault(iid, {})["_meta"] = {
                "name": rec["name"], "w": w, "h": h, "when": rec["when"]}
            self._rev += 1
            over = self.images[LAB_MAX_IMAGES:]
            self.images = self.images[:LAB_MAX_IMAGES]
        for old in over:
            self._remove_files(old["id"])
            self.runs.pop(old["id"], None)
        self._save_runs()
        return rec, None

    def _annotate(self, img, res, name, iid):
        try:
            out = img.copy()
            h, w = out.shape[:2]
            scale = max(0.4, min(1.2, w / 900.0))
            for d in res.get("dets") or []:
                x, y, bw, bh = d["box"]
                lit = (d.get("light") or {}).get("colour")
                col = (_LIGHT_BGR.get(lit) if lit and lit != "none" else None) or (0, 200, 120)
                cv2.rectangle(out, (x, y), (x + bw, y + bh), col, 2)
                tag = "%s %.2f" % (d["label"], d["conf"])
                if lit and lit != "none":
                    tag += " " + lit.upper()
                ty = y + int(20 * scale) if y < 22 * scale else y - int(6 * scale)
                cv2.putText(out, tag, (x + 2, ty), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5 * scale, (0, 0, 0), max(2, int(3 * scale)), cv2.LINE_AA)
                cv2.putText(out, tag, (x + 2, ty), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5 * scale, col, max(1, int(scale)), cv2.LINE_AA)
            light = res.get("light") or {}
            foot = "%s  |  conf %.2f  |  %dpx  |  %d found" % (
                name, res.get("conf") or 0, res.get("imgsz") or 0,
                len(res.get("dets") or []))
            if light.get("colour"):
                foot += "  |  LIGHT %s (%d%% margin)" % (
                    light["colour"].upper(), round(light.get("margin", 0) * 100))
            cv2.rectangle(out, (0, h - int(26 * scale)), (w, h), (0, 0, 0), -1)
            cv2.putText(out, foot, (6, h - int(9 * scale)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45 * scale, (235, 235, 235), max(1, int(scale)), cv2.LINE_AA)
            fn = "%s__%s.out.jpg" % (iid, _slug(name).replace(" ", "_"))
            cv2.imwrite(os.path.join(self.dir, fn), out,
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
            return fn
        except Exception as e:
            print("[lab] could not write the annotated picture: %s" % e)
            return None

    def _remove_files(self, iid):
        for suffix in (".jpg", ".thumb.jpg"):
            try:
                os.remove(os.path.join(self.dir, iid + suffix))
            except OSError:
                pass
        prefix = iid + "__"
        try:
            for fn in os.listdir(self.dir):
                if fn.startswith(prefix) and fn.endswith(".out.jpg"):
                    os.remove(os.path.join(self.dir, fn))
        except OSError:
            pass

    def delete(self, iid):
        iid = str(iid or "")
        with self._lock:
            before = len(self.images)
            self.images = [i for i in self.images if i["id"] != iid]
            if len(self.images) == before:
                return False
            self.runs.pop(iid, None)
            self._queue = [j for j in self._queue if j[0] != iid]
            self._rev += 1
        self._remove_files(iid)
        self._save_runs()
        return True

    def clear_runs(self, iid):
        with self._lock:
            meta = (self.runs.get(iid) or {}).get("_meta")
            self.runs[iid] = {"_meta": meta} if meta else {}
            self._rev += 1
        self._save_runs()
        return True

    def models(self):
        out = []
        try:
            entries = sorted(os.listdir(MODELS_DIR))
        except OSError:
            entries = []
        names = [f for f in entries if f.endswith(".pt")]
        for n in names:
            try:
                size = os.path.getsize(os.path.join(MODELS_DIR, n))
            except OSError:
                size = 0
            state = self._models.get(n)
            out.append({
                "name": n, "bytes": size,
                "colour": WALK_COLOURS[len(out) % len(WALK_COLOURS)],
                "state": "failed" if state == "FAILED" else
                         "loaded" if state is not None else "on disk",
                "classes": len(self._names.get(n) or {}) or None,
            })
        return out

    def strays(self):
        try:
            entries = sorted(os.listdir(MODELS_DIR))
        except OSError:
            return []
        return [f for f in entries
                if not f.endswith(".pt") and not f.startswith(".")][:8]

    def _model(self, name):
        m = self._models.get(name)
        if m is not None:
            if name in self._lru:
                self._lru.remove(name)
            self._lru.append(name)
            return m
        try:
            import torch
            torch.set_num_threads(1)
            from ultralytics import YOLO
            m = YOLO(os.path.join(MODELS_DIR, name))
            self._names[name] = m.names
            print("[lab] loaded %s" % name)
        except Exception as e:
            print("[lab] load failed %s: %s" % (name, e))
            m = "FAILED"
        self._models[name] = m
        self._lru.append(name)
        while len(self._lru) > 2:
            drop = self._lru.pop(0)
            if drop != name:
                self._models.pop(drop, None)
                self._names.pop(drop, None)
        return m

    def enqueue(self, iid, models, conf, imgsz):
        iid = str(iid or "")
        with self._lock:
            if not any(i["id"] == iid for i in self.images):
                return False
        have = {m["name"] for m in self.models()}
        models = [m for m in (models or []) if m in have]
        if not models:
            return False
        try:
            conf = max(0.01, min(0.95, float(conf)))
        except (TypeError, ValueError):
            conf = 0.4
        try:
            imgsz = int(max(160, min(1280, int(imgsz) // 32 * 32)))
        except (TypeError, ValueError):
            imgsz = 640
        with self._lock:
            self._queue.append((iid, models, conf, imgsz))
        return True

    def _loop(self):
        while not self._stop:
            with self._lock:
                job = self._queue.pop(0) if self._queue else None
            if job is None:
                time.sleep(0.15)
                continue
            iid, models, conf, imgsz = job
            path = os.path.join(self.dir, iid + ".jpg")
            img = cv2.imread(path)
            if img is None:
                self._note = "the picture is gone from the disk"
                continue
            for n, name in enumerate(models):
                with self._lock:
                    self._busy = {"image": iid, "model": name, "i": n + 1,
                                  "n": len(models)}
                self._run_one(iid, img, name, conf, imgsz)
            with self._lock:
                self._busy = None
                self._rev += 1
            self._save_runs()

    def _run_one(self, iid, img, name, conf, imgsz):
        t0 = time.time()
        res = {"conf": conf, "imgsz": imgsz, "when": t0, "dets": [], "error": None}
        m = self._model(name)
        if m == "FAILED":
            res["error"] = "this file did not load as a model"
        else:
            try:
                out = m.predict(img, imgsz=imgsz, conf=conf, verbose=False)[0]
                names = self._names.get(name) or {}
                for b in out.boxes:
                    cls = int(b.cls[0])
                    x1, y1, x2, y2 = [int(v) for v in b.xyxy[0].tolist()]
                    label = str(names[cls]) if cls in names else str(cls)
                    det = {
                        "label": label,
                        "conf": round(float(b.conf[0]), 3),
                        "box": [x1, y1, x2 - x1, y2 - y1],
                    }
                    if _is_light(label):
                        x1c, y1c = max(0, x1), max(0, y1)
                        x2c, y2c = min(img.shape[1], x2), min(img.shape[0], y2)
                        if x2c > x1c and y2c > y1c:
                            det["light"] = classify_light_full(
                                img[y1c:y2c, x1c:x2c])
                    res["dets"].append(det)
                res["dets"].sort(key=lambda d: -d["conf"])
                lit = [d for d in res["dets"]
                       if d.get("light") and d["light"]["colour"] != "none"]
                if lit:
                    lit.sort(key=lambda d: -(d["box"][2] * d["box"][3]))
                    res["light"] = dict(lit[0]["light"], n=len(lit))
            except Exception as e:
                res["error"] = str(e)[:200]
        res["ms"] = int((time.time() - t0) * 1000)
        if not res["error"]:
            res["out"] = self._annotate(img, res, name, iid)
        with self._lock:
            self.runs.setdefault(iid, {})[name] = res
            self._rev += 1

    def public(self):
        with self._lock:
            summary = {}
            for iid, per in self.runs.items():
                s = {}
                for mname, r in per.items():
                    if mname == "_meta" or not isinstance(r, dict):
                        continue
                    s[mname] = {"n": len(r.get("dets") or []), "ms": r.get("ms"),
                                "conf": r.get("conf"), "imgsz": r.get("imgsz"),
                                "error": r.get("error"),
                                "light": (r.get("light") or {}).get("colour"),
                                "out": r.get("out")}
                if s:
                    summary[iid] = s
            return {
                "images": [dict(i) for i in self.images],
                "models": self.models(),
                "strays": self.strays(),
                "busy": dict(self._busy) if self._busy else None,
                "queued": len(self._queue),
                "rev": self._rev,
                "note": self._note,
                "max_images": LAB_MAX_IMAGES,
                "max_mb": LAB_MAX_UPLOAD_BYTES // (1 << 20),
                "summary": summary,
            }

    def detections(self, iid):
        with self._lock:
            per = dict(self.runs.get(str(iid or "")) or {})
            vocab = {n: sorted(str(v) for v in (self._names.get(n) or {}).values())
                     for n in per if n != "_meta"}
        per.pop("_meta", None)
        return {"image": iid, "runs": per, "vocab": vocab}

    def export(self, iid):
        iid = str(iid or "")
        with self._lock:
            img = next((dict(i) for i in self.images if i["id"] == iid), None)
            per = {k: v for k, v in (self.runs.get(iid) or {}).items() if k != "_meta"}
            vocab = {n: sorted(str(v) for v in (self._names.get(n) or {}).values())
                     for n in per}
        if not img:
            return None
        return {
            "image": img,
            "files": {
                "original": "/lab/%s.jpg" % iid,
                "thumb": "/lab/%s.thumb.jpg" % iid,
                "annotated": {n: "/lab/%s" % r["out"]
                              for n, r in per.items() if r.get("out")},
            },
            "runs": per,
            "vocab": vocab,
        }

    def shutdown(self):
        self._stop = True
        self._save_runs()
