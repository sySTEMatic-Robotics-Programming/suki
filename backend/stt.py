import os
import shutil
import subprocess
import tempfile
import wave

import config

_TMPDIR = "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()
TMP_WAV = os.path.join(_TMPDIR, "suki-utterance.wav")


class Recognizer:
    def __init__(self, settings=None):
        self.binary = config.WHISPER_BIN
        self.settings = settings
        self.error = ""
        self.last_ms = 0
        self._nice = (["nice", "-n", str(config.WHISPER_NICE)]
                      if config.WHISPER_NICE and shutil.which("nice") else [])

    @property
    def model(self):
        name = ""
        try:
            name = os.path.basename(str(self.settings["stt_model"]) if self.settings
                                    else "")
        except (KeyError, TypeError):
            name = ""
        if name:
            p = os.path.join(config.WHISPER_MODEL_DIR, name)
            if os.path.isfile(p):
                return p
        return config.WHISPER_MODEL

    @property
    def available(self):
        return os.path.exists(self.binary) and os.path.exists(self.model)

    def models(self):
        out = []
        try:
            names = sorted(n for n in os.listdir(config.WHISPER_MODEL_DIR)
                           if n.endswith(".bin"))
        except OSError:
            return out
        cur = os.path.basename(self.model)
        for n in names[:config.WHISPER_MODEL_MAX]:
            try:
                size = os.path.getsize(os.path.join(config.WHISPER_MODEL_DIR, n))
            except OSError:
                continue
            out.append({"name": n, "mb": round(size / (1 << 20), 1), "on": n == cur})
        return out

    def transcribe(self, pcm, lang, prompt=""):
        if not self.available:
            return ""
        with wave.open(TMP_WAV, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(config.MIC_RATE)
            w.writeframes(pcm.tobytes())

        cmd = self._nice + [self.binary, "-m", self.model, "-f", TMP_WAV,
                            "-t", str(config.WHISPER_THREADS), "-nt", "-np"]
        if config.WHISPER_GREEDY:
            cmd += ["-bo", "1", "-bs", "1"]
        if config.WHISPER_NO_FALLBACK:
            cmd += ["-nf"]
        if lang in config.LANGS:
            cmd += ["-l", lang]
        if prompt:
            cmd += ["--prompt", prompt]

        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=config.WHISPER_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.error = "whisper timed out after %ds" % config.WHISPER_TIMEOUT_S
            return ""
        except OSError as e:
            self.error = str(e)[:200]
            return ""

        if r.returncode != 0:
            err = (r.stderr or "").strip()
            self.error = (err.splitlines()[-1][:200] if err
                          else "whisper exited %d" % r.returncode)
            return ""
        self.error = ""
        text = " ".join(r.stdout.split())
        if text.startswith(("[", "(")) and text.endswith(("]", ")")):
            return ""
        return text

    def state(self):
        err = self.error
        if not self.available and not err:
            missing = ("whisper-cli" if not os.path.exists(self.binary)
                       else os.path.basename(self.model))
            err = "%s not found (SIM) — run ./setup_voice.sh" % missing
        return {"available": self.available, "model": os.path.basename(self.model),
                "error": err, "ms": self.last_ms,
                "models": self.models(), "dir": config.WHISPER_MODEL_DIR}
