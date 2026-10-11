import json
import os

from config import (LEGS, SAFE_MAX_US, SAFE_MIN_US, SKETCH_COLOURS,
                    SKETCH_MAX_POINTS, SKETCH_MAX_STROKES, SKETCH_WIDTHS)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _colour(v):
    v = str(v or "").lower()
    return v if v in SKETCH_COLOURS else SKETCH_COLOURS[0]


def _width(v):
    w = _num(v, SKETCH_WIDTHS[1])
    return min(SKETCH_WIDTHS, key=lambda x: abs(x - w))


def _stroke(raw):
    if not isinstance(raw, dict):
        raw = {}
    pts = raw.get("pts")
    out = []
    if isinstance(pts, list):
        for p in pts[:SKETCH_MAX_POINTS]:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            out.append([round(_clamp(_num(p[0]), SAFE_MIN_US, SAFE_MAX_US), 1),
                        round(_clamp(_num(p[1]), SAFE_MIN_US, SAFE_MAX_US), 1)])
    return {"colour": _colour(raw.get("colour")), "w": _width(raw.get("w")),
            "pts": out}


class SketchStore:
    def __init__(self, path, write_json):
        self.path = path
        self._write = write_json
        self.legs = {leg: [] for leg in LEGS}
        self._dirty = False
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for leg in LEGS:
            src = raw.get(leg)
            if not isinstance(src, list):
                continue
            self.legs[leg] = [s for s in (_stroke(x) for x in src[-SKETCH_MAX_STROKES:])
                              if len(s["pts"]) >= 2]

    def save(self):
        self._write(self.path, self.legs)
        self._dirty = False

    def touch(self):
        self._dirty = True

    def flush(self):
        if not self._dirty:
            return
        try:
            self.save()
        except OSError as e:
            print("[sketch] could not write %s: %s" % (self.path, e))
            self._dirty = False

    def add(self, leg, stroke):
        if leg not in LEGS:
            return False
        s = _stroke(stroke)
        if len(s["pts"]) < 2:
            return False
        pts = self.legs[leg]
        pts.append(s)
        if len(pts) > SKETCH_MAX_STROKES:
            del pts[:len(pts) - SKETCH_MAX_STROKES]
        self.touch()
        return True

    def undo(self, leg):
        if leg not in LEGS or not self.legs[leg]:
            return False
        self.legs[leg].pop()
        self.touch()
        return True

    def erase(self, leg, index):
        if leg not in LEGS:
            return False
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        if not 0 <= index < len(self.legs[leg]):
            return False
        del self.legs[leg][index]
        self.touch()
        return True

    def clear(self, leg=None):
        if leg in LEGS:
            if not self.legs[leg]:
                return False
            self.legs[leg] = []
        else:
            self.legs = {k: [] for k in LEGS}
        self.touch()
        return True

    def public(self):
        return {
            "legs": {leg: [dict(s) for s in self.legs.get(leg, [])] for leg in LEGS},
            "palette": list(SKETCH_COLOURS),
            "widths": list(SKETCH_WIDTHS),
            "max_strokes": SKETCH_MAX_STROKES,
        }


def demo():
    import tempfile

    written = {}

    def fake_write(path, data):
        written[path] = json.loads(json.dumps(data))

    path = os.path.join(tempfile.gettempdir(), "sketch-selfcheck.json")
    if os.path.exists(path):
        os.remove(path)
    s = SketchStore(path, fake_write)
    leg = LEGS[0]

    assert s.public()["legs"][leg] == []
    assert s.add(leg, {"pts": [[1500, 1500]]}) is False
    assert s.add(leg, {"colour": "javascript:x", "w": 999,
                       "pts": [[1500, 1500], [1600, 1400]]}) is True
    got = s.public()["legs"][leg][0]
    assert got["colour"] in SKETCH_COLOURS, got["colour"]
    assert got["w"] in SKETCH_WIDTHS, got["w"]
    s.add(leg, {"pts": [[-1e9, 1e9], [1500, 1500]]})
    p = s.public()["legs"][leg][1]["pts"][0]
    assert SAFE_MIN_US <= p[0] <= SAFE_MAX_US and SAFE_MIN_US <= p[1] <= SAFE_MAX_US, p
    for i in range(SKETCH_MAX_STROKES + 10):
        assert s.add(leg, {"pts": [[1500 + i, 1500], [1600, 1400]]}) is True
    assert len(s.public()["legs"][leg]) == SKETCH_MAX_STROKES
    s.add(leg, {"pts": [[1500, 1500]] * (SKETCH_MAX_POINTS + 50)})
    assert len(s.public()["legs"][leg][-1]["pts"]) == SKETCH_MAX_POINTS
    n = len(s.public()["legs"][leg])
    assert s.undo(leg) is True and len(s.public()["legs"][leg]) == n - 1
    assert s.erase(leg, 0) is True and len(s.public()["legs"][leg]) == n - 2
    assert s.erase(leg, 9999) is False
    assert s.clear(leg) is True and s.public()["legs"][leg] == []
    assert s.clear(leg) is False
    s.add(leg, {"pts": [[1500, 1500], [1600, 1400]]})
    s.flush()
    assert path in written and len(written[path][leg]) == 1
    written.clear()
    s.flush()
    assert not written, "flush wrote with nothing dirty"
    print("sketch.py self-check ok")


if __name__ == "__main__":
    demo()
