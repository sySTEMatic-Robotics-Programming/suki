import json
import os

from config import CHANNELS, ACTION_SEED, SAFE_MIN_US, SAFE_MAX_US

_CHSET = set(CHANNELS)


def _clean_pos(raw):
    out = {}
    for k, v in (raw or {}).items():
        try:
            ch, us = int(k), int(round(float(v)))
        except (TypeError, ValueError):
            continue
        if ch in _CHSET:
            out[ch] = max(SAFE_MIN_US, min(SAFE_MAX_US, us))
    return out


class ActionStore:
    def __init__(self, path, write_json):
        self.path = path
        self._write = write_json
        self.actions = []
        self._next_id = 1
        self._load()

    def _load(self):
        raw = None
        try:
            with open(self.path) as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = None
        if not isinstance(raw, dict) or not isinstance(raw.get("actions"), list):
            self.actions = [{"id": i + 1, "name": a["name"],
                             "pos": _clean_pos(a["pos"])}
                            for i, a in enumerate(ACTION_SEED)]
            self._next_id = len(self.actions) + 1
            self.save()
            print("[suki] seeded %s with %d actions"
                  % (os.path.basename(self.path), len(self.actions)))
            return
        for a in raw["actions"]:
            if not isinstance(a, dict):
                continue
            self.actions.append({
                "id": int(a.get("id") or self._next_id),
                "name": str(a.get("name") or "action"),
                "pos": _clean_pos(a.get("pos")),
            })
        for a in self.actions:
            self._next_id = max(self._next_id, a["id"] + 1)

    def save(self):
        self._write(self.path, {"actions": [
            {"id": a["id"], "name": a["name"],
             "pos": {str(ch): int(us) for ch, us in sorted(a["pos"].items())}}
            for a in self.actions]})

    def get(self, aid):
        try:
            aid = int(aid)
        except (TypeError, ValueError):
            return None
        for a in self.actions:
            if a["id"] == aid:
                return a
        return None

    def public(self):
        return [{"id": a["id"], "name": a["name"],
                 "pos": {str(ch): int(us) for ch, us in a["pos"].items()}}
                for a in self.actions]

    def add(self, name=None, pos=None):
        a = {"id": self._next_id, "name": str(name or "action %d" % self._next_id),
             "pos": _clean_pos(pos)}
        self._next_id += 1
        self.actions.append(a)
        self.save()
        return a

    def rename(self, aid, name):
        a = self.get(aid)
        if a is None:
            return None
        a["name"] = str(name or "")[:48] or a["name"]
        self.save()
        return a

    def set_channel(self, aid, ch, us):
        a = self.get(aid)
        if a is None:
            return None
        try:
            ch, us = int(ch), int(round(float(us)))
        except (TypeError, ValueError):
            return None
        if ch not in _CHSET:
            return None
        a["pos"][ch] = max(SAFE_MIN_US, min(SAFE_MAX_US, us))
        self.save()
        return a

    def swap_channels(self, a, b):
        if a == b:
            return False
        for act in self.actions:
            pos = act["pos"]
            va, vb = pos.get(a), pos.get(b)
            for ch, v in ((a, vb), (b, va)):
                if v is None:
                    pos.pop(ch, None)
                else:
                    pos[ch] = v
        self.save()
        return True

    def delete(self, aid):
        a = self.get(aid)
        if a is None:
            return False
        self.actions.remove(a)
        self.save()
        return True
