import json
import os
import threading
import time

_LEVELS = ("cmd", "pwm", "err", "info")


class Log:
    def __init__(self, path, max_bytes=4 * 1024 * 1024, pwm=True):
        self.path = path
        self.max_bytes = int(max_bytes)
        self.pwm_enabled = bool(pwm)
        self._buf = []
        self._lock = threading.Lock()
        self._t0 = time.time()
        self._m0 = time.monotonic()
        self._dropped = 0
        try:
            if os.path.exists(self.path):
                os.replace(self.path, self.path + ".1")
        except OSError:
            pass

    def event(self, level, kind, **fields):
        if level == "pwm" and not self.pwm_enabled:
            return
        fields["lv"] = level
        fields["k"] = kind
        fields["t"] = round(self._t0 + (time.monotonic() - self._m0), 4)
        with self._lock:
            if len(self._buf) > 20000:
                self._dropped += 1
                return
            self._buf.append(fields)

    def cmd(self, kind, **f):
        self.event("cmd", kind, **f)

    def pwm(self, **f):
        self.event("pwm", "pwm", **f)

    def err(self, kind, **f):
        self.event("err", kind, **f)

    def info(self, kind, **f):
        self.event("info", kind, **f)

    def flush(self):
        with self._lock:
            buf, self._buf = self._buf, []
            dropped, self._dropped = self._dropped, 0
        if not buf and not dropped:
            return
        if dropped:
            buf.append({"lv": "err", "k": "log_overflow", "n": dropped,
                        "t": round(time.time(), 4)})
        try:
            self._rotate()
            with open(self.path, "a") as f:
                for ev in buf:
                    f.write(json.dumps(ev, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def _rotate(self):
        try:
            if os.path.getsize(self.path) < self.max_bytes:
                return
        except OSError:
            return
        try:
            os.replace(self.path, self.path + ".1")
        except OSError:
            pass

    def tail(self, n=200, level=None):
        self.flush()
        out = []
        try:
            with open(self.path) as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if level and ev.get("lv") != level:
                        continue
                    out.append(ev)
                    if len(out) > n * 4:
                        del out[:len(out) - n]
        except OSError:
            return []
        return out[-n:]
