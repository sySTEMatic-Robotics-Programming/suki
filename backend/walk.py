import json
import os

from config import (LEGS, SAFE_MAX_US, SAFE_MIN_US, WALK_COLOURS, WALK_DWELL_MAX,
                    WALK_MAX_POINTS, WALK_MAX_SETS, WALK_SEED)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _point(raw):
    if not isinstance(raw, dict):
        raw = {}
    return {
        "thigh": int(_clamp(_num(raw.get("thigh"), SAFE_MIN_US),
                            SAFE_MIN_US, SAFE_MAX_US)),
        "k": round(_clamp(_num(raw.get("k"), 0.5), 0.0, 1.0), 4),
        "dwell": round(_clamp(_num(raw.get("dwell"), 0.0), 0.0, WALK_DWELL_MAX), 2),
    }


def _colour(v, fallback=None):
    v = str(v or "").lower()
    if v in WALK_COLOURS:
        return v
    return fallback if fallback in WALK_COLOURS else WALK_COLOURS[0]


def _name(v, fallback):
    v = str(v or "").strip()[:32]
    return v or fallback


class WalkStore:
    def __init__(self, path, write_json):
        self.path = path
        self._write = write_json
        self.sets = []
        self._next_id = 1
        self._dirty = False
        self._load()

    def _load(self):
        raw = None
        try:
            with open(self.path) as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = None
        if not isinstance(raw, dict) or not isinstance(raw.get("sets"), list):
            self.sets = [self._make(s.get("name"), s.get("colour"), s.get("legs"))
                         for s in WALK_SEED]
            self.save()
            print("[suki] seeded %s with %d walking-point set(s)"
                  % (os.path.basename(self.path), len(self.sets)))
            return
        for s in raw["sets"]:
            if not isinstance(s, dict):
                continue
            self.sets.append(self._make(s.get("name"), s.get("colour"),
                                        s.get("legs"), s.get("id")))
        if not self.sets:
            self.sets = [self._make("forward", WALK_COLOURS[0], None)]

    def _make(self, name, colour, legs, sid=None):
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            sid = None
        if sid is None or sid < 1:
            sid = self._next_id
        self._next_id = max(self._next_id, sid + 1)
        legs = legs if isinstance(legs, dict) else {}
        return {
            "id": sid,
            "name": _name(name, "set %d" % sid),
            "colour": _colour(colour, WALK_COLOURS[(sid - 1) % len(WALK_COLOURS)]),
            "legs": {leg: [_point(p) for p in (legs.get(leg) or [])][:WALK_MAX_POINTS]
                     for leg in LEGS},
        }

    def save(self):
        self._write(self.path, {"sets": self.sets})
        self._dirty = False

    def touch(self):
        self._dirty = True

    def flush(self):
        if not self._dirty:
            return
        try:
            self.save()
        except OSError as e:
            print("[walk] could not write %s: %s" % (self.path, e))
            self._dirty = False

    def get(self, sid):
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            return None
        for s in self.sets:
            if s["id"] == sid:
                return s
        return None

    def _pts(self, sid, leg):
        s = self.get(sid)
        if s is None or leg not in LEGS:
            return None
        return s["legs"].setdefault(leg, [])

    def public(self):
        return {
            "sets": [{"id": s["id"], "name": s["name"], "colour": s["colour"],
                      "legs": {leg: [dict(p) for p in s["legs"].get(leg, [])]
                               for leg in LEGS}}
                     for s in self.sets],
            "palette": list(WALK_COLOURS),
            "max_sets": WALK_MAX_SETS,
            "max_points": WALK_MAX_POINTS,
            "dwell_max": WALK_DWELL_MAX,
        }

    def add_set(self, name=None, copy_of=None):
        if len(self.sets) >= WALK_MAX_SETS:
            return None
        src = self.get(copy_of)
        legs = {leg: [dict(p) for p in src["legs"].get(leg, [])] for leg in LEGS} \
            if src else None
        s = self._make(name or (src and src["name"] + " copy") or None,
                       WALK_COLOURS[len(self.sets) % len(WALK_COLOURS)], legs)
        self.sets.append(s)
        self.touch()
        return s

    def rename_set(self, sid, name):
        s = self.get(sid)
        if s is None:
            return None
        s["name"] = _name(name, s["name"])
        self.touch()
        return s

    def recolour_set(self, sid, colour):
        s = self.get(sid)
        if s is None:
            return None
        s["colour"] = _colour(colour, s["colour"])
        self.touch()
        return s

    def delete_set(self, sid):
        s = self.get(sid)
        if s is None:
            return False
        if len(self.sets) <= 1:
            s["legs"] = {leg: [] for leg in LEGS}
        else:
            self.sets.remove(s)
        self.touch()
        return True

    def add_point(self, sid, leg, thigh, k, index=None):
        pts = self._pts(sid, leg)
        if pts is None or len(pts) >= WALK_MAX_POINTS:
            return None
        p = _point({"thigh": thigh, "k": k})
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = None
        if index is None or index < 0 or index > len(pts):
            pts.append(p)
        else:
            pts.insert(index, p)
        self.touch()
        return p

    def set_point(self, sid, leg, index, thigh=None, k=None, dwell=None):
        pts = self._pts(sid, leg)
        try:
            index = int(index)
        except (TypeError, ValueError):
            return None
        if pts is None or not (0 <= index < len(pts)):
            return None
        p = pts[index]
        merged = dict(p)
        if thigh is not None:
            merged["thigh"] = thigh
        if k is not None:
            merged["k"] = k
        if dwell is not None:
            merged["dwell"] = dwell
        pts[index] = _point(merged)
        self.touch()
        return pts[index]

    def delete_point(self, sid, leg, index):
        pts = self._pts(sid, leg)
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        if pts is None or not (0 <= index < len(pts)):
            return False
        pts.pop(index)
        self.touch()
        return True

    def move_point(self, sid, leg, index, delta):
        pts = self._pts(sid, leg)
        try:
            index, delta = int(index), int(delta)
        except (TypeError, ValueError):
            return False
        if pts is None or not (0 <= index < len(pts)) or not delta:
            return False
        p = pts.pop(index)
        pts.insert(int(_clamp(index + delta, 0, len(pts))), p)
        self.touch()
        return True

    def clear(self, sid, leg):
        pts = self._pts(sid, leg)
        if pts is None:
            return False
        pts.clear()
        self.touch()
        return True

    def copy_leg(self, sid, src, dst):
        s = self.get(sid)
        if s is None or src not in LEGS or dst not in LEGS or src == dst:
            return False
        s["legs"][dst] = [dict(p) for p in s["legs"].get(src, [])][:WALK_MAX_POINTS]
        self.touch()
        return True
