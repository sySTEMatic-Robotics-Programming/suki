import difflib
import json
import os
import unicodedata

import config

BUILTIN_TARGETS = {
    "engage": "Hold position (engage)",
    "relax": "Relax (go limp)",
    "estop": "EMERGENCY STOP",
    "clear_estop": "Release the E-STOP",
    "return_to_last": "Return to last position",
    "pose_record": "Record current position as a new pose",
    "record_start": "Start the audio recording",
    "record_stop": "Stop the audio recording",
    "record_toggle": "Start/stop the audio recording",
}


def write_json(path, data):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def normalize(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = "".join(c if (c.isalnum() or c.isspace()) else " " for c in s)
    return " ".join(s.split())


def score(phrase, text):
    n, t = normalize(phrase), normalize(text)
    if not n or not t:
        return 0.0
    if n in t:
        return 1.0
    return difflib.SequenceMatcher(None, n, t).ratio()


class Settings:

    def __init__(self, path):
        self.path = path
        self._d = dict(config.SETTINGS_SEED)
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in self._d:
                        self._d[k] = v
        except (OSError, ValueError):
            pass
        self._d = {k: self._coerce(k, v) for k, v in self._d.items()}
        self.save()

    @staticmethod
    def _clamp(v, lo_hi):
        lo, hi = lo_hi
        return max(lo, min(hi, float(v)))

    def _coerce(self, key, value, fallback=None):
        seed = config.SETTINGS_SEED[key] if fallback is None else fallback
        try:
            if key == "gain":
                return self._clamp(value, config.GAIN_RANGE)
            if key == "threshold":
                return self._clamp(value, config.THRESHOLD_RANGE)
            if key == "fuzz":
                return self._clamp(value, config.FUZZ_RANGE)
            if key == "stt_lang":
                return str(value) if str(value) in config.LANGS + ("auto",) else seed
            if key == "stt_model":
                v = os.path.basename(str(value).strip())
                if not v:
                    return ""
                ok = (v.endswith(".bin") and
                      os.path.isfile(os.path.join(config.WHISPER_MODEL_DIR, v)))
                return v if ok else seed
            if key == "mic_device":
                v = str(value).strip()
                ok = v and len(v) <= config.MIC_DEVICE_MAX_LEN and all(
                    c.isalnum() or c in "_-.:,=" for c in v)
                return v if ok else seed
            if key == "mic_channel":
                return 1 if int(value) else 0
            return bool(value)
        except (TypeError, ValueError):
            return seed

    def __getitem__(self, key):
        return self._d[key]

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        if key not in config.SETTINGS_SEED:
            return None
        self._d[key] = self._coerce(key, value, fallback=self._d[key])
        self.save()
        return self._d[key]

    def public(self):
        return dict(self._d)

    def save(self):
        write_json(self.path, self._d)


def _clean_langmap(raw, as_list):
    out = {}
    for lang in config.LANGS:
        v = (raw or {}).get(lang)
        if as_list:
            items = v if isinstance(v, list) else ([v] if isinstance(v, str) else [])
            out[lang] = [str(x).strip() for x in items if str(x).strip()]
        else:
            out[lang] = str(v).strip() if isinstance(v, str) else ""
    return out


def _clean_target(raw):
    t = str(raw or "").strip()
    if t in BUILTIN_TARGETS:
        return t
    if t.startswith("pose:"):
        try:
            return "pose:%d" % int(t[5:])
        except ValueError:
            return ""
    if t.startswith("seq:"):
        try:
            return "seq:%d" % int(t[4:])
        except ValueError:
            return ""
    return ""


class CommandStore:
    def __init__(self, path):
        self.path = path
        self.commands = []
        self._next_id = 1
        self._load()

    def _load(self):
        raw = None
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = None
        if not isinstance(raw, dict) or not isinstance(raw.get("commands"), list):
            self.commands = [self._clean(dict(c, id=i + 1))
                             for i, c in enumerate(config.COMMAND_SEED)]
            self._next_id = len(self.commands) + 1
            self.save()
            print("[suki] seeded %s with %d voice commands"
                  % (os.path.basename(self.path), len(self.commands)))
            return
        for c in raw["commands"]:
            if isinstance(c, dict):
                self.commands.append(self._clean(c))
        for c in self.commands:
            self._next_id = max(self._next_id, c["id"] + 1)

    def _clean(self, c):
        try:
            cid = int(c.get("id") or self._next_id)
        except (TypeError, ValueError):
            cid = self._next_id
        return {
            "id": cid,
            "enabled": bool(c.get("enabled", True)),
            "label": _clean_langmap(c.get("label"), as_list=False),
            "phrases": _clean_langmap(c.get("phrases"), as_list=True),
            "target": _clean_target(c.get("target")),
        }

    def save(self):
        write_json(self.path, {"commands": self.commands})

    def public(self):
        return [dict(c) for c in self.commands]

    def get(self, cid):
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return None
        for c in self.commands:
            if c["id"] == cid:
                return c
        return None

    def prompt(self, lang):
        langs = config.LANGS if lang not in config.LANGS else (lang,)
        seen, out = set(), []
        for lg in langs:
            for c in self.commands:
                if not c["enabled"]:
                    continue
                for p in c["phrases"].get(lg, []):
                    if p not in seen:
                        seen.add(p)
                        out.append(p)
        return ". ".join(out) + ("." if out else "")

    def match(self, text, fuzz):
        best, key, second = None, (0.0, 0), 0.0
        for c in self.commands:
            if not c["enabled"]:
                continue
            top, toplen = 0.0, 0
            for lg in config.LANGS:
                for p in c["phrases"].get(lg, []):
                    s, n = score(p, text), len(normalize(p))
                    if (s, n) > (top, toplen):
                        top, toplen = s, n
            k = (top, toplen)
            if k > key:
                best, key, second = c, k, key[0]
            elif top > second:
                second = top

        if key[0] < fuzz:
            return None, key[0], "no_match"
        if key[0] < 1.0 and key[0] - second < config.MATCH_MARGIN:
            return None, key[0], "ambiguous"
        return best, key[0], ""

    def add(self):
        c = self._clean({"id": self._next_id, "enabled": False,
                         "label": {lg: "new command" for lg in config.LANGS}})
        self._next_id += 1
        self.commands.append(c)
        self.save()
        return c

    def update(self, cid, field, value, lang=None):
        c = self.get(cid)
        if c is None:
            return None
        if field == "enabled":
            c["enabled"] = bool(value)
        elif field == "target":
            c["target"] = _clean_target(value)
        elif field == "label" and lang in config.LANGS:
            c["label"][lang] = str(value or "").strip()[:64]
        elif field == "phrases" and lang in config.LANGS:
            c["phrases"][lang] = [p.strip() for p in str(value or "").splitlines()
                                  if p.strip()]
        else:
            return None
        self.save()
        return c

    def delete(self, cid):
        c = self.get(cid)
        if c is None:
            return False
        self.commands.remove(c)
        self.save()
        return True
