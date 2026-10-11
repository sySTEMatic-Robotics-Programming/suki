import os
import re
import shutil
import subprocess
import threading
import time
import wave
from collections import deque

import numpy as np

import config


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float32) ** 2)))


_CARD_RE = re.compile(r"^card (\d+): (\S+) \[([^\]]*)\], device (\d+): (.*)$")


def list_devices():
    if shutil.which("arecord") is None:
        return []
    try:
        out = subprocess.run(["arecord", "-l"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    devices = []
    for line in out.splitlines():
        m = _CARD_RE.match(line.strip())
        if not m:
            continue
        _idx, name, long_name, dev, desc = m.groups()
        devices.append({
            "device": "plughw:CARD=%s,DEV=%s" % (name, dev),
            "label": "%s — %s" % (long_name or name, desc.split("[")[0].strip()),
        })
    return devices


class Microphone:
    def __init__(self, settings):
        self.settings = settings
        self.available = shutil.which("arecord") is not None
        self.error = "" if self.available else "arecord not found (SIM)"
        self.level = 0.0
        self.speaking = False
        self.devices = list_devices()
        self.device = str(settings["mic_device"])
        self.switched = False
        self._proc = None
        self._stop = False
        self._taps = []
        self._taps_lock = threading.Lock()

    def refresh(self):
        self.devices = list_devices()
        return self.devices

    def tap(self, maxlen):
        d = deque(maxlen=int(maxlen))
        with self._taps_lock:
            self._taps.append(d)
        return d

    def untap(self, d):
        with self._taps_lock:
            if d in self._taps:
                self._taps.remove(d)

    def _feed(self, chunk):
        with self._taps_lock:
            for t in self._taps:
                t.append(chunk)

    def chunks(self):
        self._stop = False
        self.switched = False
        self.device = str(self.settings["mic_device"])
        cmd = ["arecord", "-q", "-D", self.device,
               "-c", str(config.MIC_CHANNELS), "-r", str(config.MIC_RATE),
               "-f", "S16_LE", "-t", "raw", "-"]
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)
        except OSError as e:
            self.error = str(e)[:200]
            return
        nbytes = config.MIC_CHUNK * config.MIC_CHANNELS * 2
        first = True
        try:
            while not self._stop:
                buf = self._proc.stdout.read(nbytes)
                if len(buf) < nbytes:
                    break
                if first:
                    first, self.error = False, ""
                if str(self.settings["mic_device"]) != self.device:
                    self.switched = True
                    break
                ch = int(self.settings["mic_channel"]) % config.MIC_CHANNELS
                raw = np.frombuffer(buf, "<i2")[ch::config.MIC_CHANNELS]
                amped = raw.astype(np.int32) * float(self.settings["gain"])
                chunk = np.clip(amped, -32768, 32767).astype("<i2")
                self.level = rms(chunk)
                self._feed(chunk)
                yield chunk
        finally:
            self.level = 0.0
            self.speaking = False
            self._drain_error()
            self.stop()

    def _drain_error(self):
        if self._proc is None or self.switched:
            return
        try:
            err = (self._proc.stderr.read() or b"").decode("utf-8", "replace").strip()
        except Exception:
            err = ""
        if err and self._proc.returncode not in (0, None):
            self.error = err.splitlines()[-1][:200]

    def utterances(self):
        if not self.available:
            return
        dt = config.MIC_CHUNK / config.MIC_RATE
        pre = deque(maxlen=config.PREROLL_CHUNKS)
        buf, quiet = [], 0.0

        for c in self.chunks():
            loud = self.level > float(self.settings["threshold"])
            if not self.speaking:
                pre.append(c)
                if loud:
                    self.speaking, buf, quiet = True, list(pre), 0.0
                    pre.clear()
                continue

            buf.append(c)
            quiet = 0.0 if loud else quiet + dt
            if quiet >= config.SILENCE_S or len(buf) * dt > config.MAX_UTTERANCE_S:
                seg = np.concatenate(buf)
                buf, quiet, self.speaking = [], 0.0, False
                if len(seg) / config.MIC_RATE >= config.MIN_UTTERANCE_S:
                    yield seg

    def stop(self):
        self._stop = True
        p, self._proc = self._proc, None
        if p is not None:
            try:
                p.terminate()
                p.wait(timeout=1)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def state(self):
        return {"available": self.available, "device": self.device,
                "devices": self.devices, "channel": int(self.settings["mic_channel"]),
                "level": round(self.level, 1), "speaking": self.speaking,
                "error": self.error}


def wav_header(data_bytes):
    rate = config.MIC_RATE
    byte_rate = rate * 2
    return (b"RIFF" + int(data_bytes + 36).to_bytes(4, "little") + b"WAVEfmt "
            + (16).to_bytes(4, "little")
            + (1).to_bytes(2, "little")
            + (1).to_bytes(2, "little")
            + rate.to_bytes(4, "little")
            + byte_rate.to_bytes(4, "little")
            + (2).to_bytes(2, "little")
            + (16).to_bytes(2, "little")
            + b"data" + int(data_bytes).to_bytes(4, "little"))


class Recorder:

    def __init__(self, mic, directory):
        self.mic = mic
        self.dir = directory
        self.on = False
        self.path = None
        self.started = 0.0
        self.error = ""
        self._thread = None
        self._tap = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._files = []
        self._files_at = -1e9

    def files(self):
        now = time.monotonic()
        if now - self._files_at < 1.0:
            return self._files
        self._files_at = now
        busy = os.path.basename(self.path) if (self.on and self.path) else None
        try:
            names = [n for n in os.listdir(self.dir)
                     if n.endswith(".wav") and n != busy]
        except OSError:
            self._files = []
            return self._files
        out = []
        for n in names:
            try:
                st = os.stat(os.path.join(self.dir, n))
            except OSError:
                continue
            out.append({"name": n, "bytes": int(st.st_size), "t": st.st_mtime,
                        "seconds": round(max(0, st.st_size - 44)
                                         / (config.MIC_RATE * 2), 1)})
        out.sort(key=lambda r: -r["t"])
        self._files = out
        return out

    def _forget_files(self):
        self._files_at = -1e9

    def _prune(self, keep):
        self._forget_files()
        for row in self.files()[max(0, int(keep)):]:
            try:
                os.remove(os.path.join(self.dir, row["name"]))
            except OSError:
                pass
        self._forget_files()

    def start(self):
        with self._lock:
            if self.on:
                return False, "already recording"
            if not self.mic.available:
                self.error = "no microphone on this machine (SIM)"
                return False, self.error
            try:
                os.makedirs(self.dir, exist_ok=True)
            except OSError as e:
                self.error = str(e)[:160]
                return False, self.error
            self._prune(config.RECORD_KEEP - 1)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            name = "suki-%s.wav" % stamp
            n = 1
            while os.path.exists(os.path.join(self.dir, name)):
                n += 1
                name = "suki-%s-%d.wav" % (stamp, n)
            self.path = os.path.join(self.dir, name)
            self.started = time.time()
            self.error = ""
            self._stop.clear()
            self._tap = self.mic.tap(config.RECORD_QUEUE_CHUNKS)
            self.on = True
            self._thread = threading.Thread(target=self._run, name="recorder",
                                            daemon=True)
            self._thread.start()
        return True, name

    def stop(self):
        with self._lock:
            if not self.on:
                return False, "not recording"
            self.on = False
            self._stop.set()
            t, self._thread = self._thread, None
        if t is not None:
            t.join(timeout=3)
        self._forget_files()
        return True, os.path.basename(self.path or "")

    def toggle(self):
        return self.stop() if self.on else self.start()

    def _run(self):
        tap, path = self._tap, self.path
        try:
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(config.MIC_RATE)
                while True:
                    done = self._stop.is_set()
                    wrote = False
                    while tap:
                        w.writeframes(tap.popleft().tobytes())
                        wrote = True
                    if done and not wrote:
                        break
                    if time.time() - self.started > config.RECORD_MAX_S:
                        self.error = ("stopped at the %d s limit"
                                      % config.RECORD_MAX_S)
                        break
                    if not wrote:
                        time.sleep(0.05)
        except (OSError, ValueError) as e:
            self.error = str(e)[:160]
        finally:
            self.mic.untap(tap)
            self.on = False
            self._stop.set()

    def state(self):
        return {"on": bool(self.on), "error": self.error,
                "file": os.path.basename(self.path) if (self.on and self.path) else None,
                "seconds": round(time.time() - self.started, 1) if self.on else 0.0,
                "max_s": config.RECORD_MAX_S, "files": self.files()}
