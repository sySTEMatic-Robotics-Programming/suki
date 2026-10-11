import threading
import time
from collections import deque

import config
from audio import Microphone
from stt import Recognizer


class Listener:
    def __init__(self, settings, commands, robot=None, recorder=None,
                 sequences=None):
        self.settings = settings
        self.commands = commands
        self.robot = robot
        self.recorder = recorder
        self.sequences = sequences
        self.mic = Microphone(settings)
        self.stt = Recognizer(settings)
        self.transcript = deque(maxlen=config.TRANSCRIPT_MAX)
        self.heard = 0
        self.fired = 0
        self.thinking = False
        self.think_since = 0.0
        self._last_fire = {}
        self._lock = threading.Lock()
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="voice", daemon=True)
        self._thread.start()

    @property
    def mode(self):
        return "MIC" if (self.mic.available and self.stt.available) else "SIM"

    @property
    def alive(self):
        return not self._stop

    def _loop(self):
        while not self._stop:
            try:
                for pcm in self.mic.utterances():
                    if self._stop:
                        return
                    if not self.settings["listening"]:
                        continue
                    lang = self.settings["stt_lang"]
                    t0 = time.monotonic()
                    with self._lock:
                        self.thinking = True
                        self.think_since = time.time()
                    try:
                        text = self.stt.transcribe(pcm, lang,
                                                   self.commands.prompt(lang))
                    finally:
                        with self._lock:
                            self.thinking = False
                    self.stt.last_ms = int((time.monotonic() - t0) * 1000)
                    if text:
                        self.hear(text, source="mic")
            except Exception as e:
                self.mic.error = str(e)[:200]
            if self._stop:
                return
            time.sleep(0.2 if self.mic.switched else 2.0)

    def hear(self, text, source="mic"):
        cmd, sc, why = self.commands.match(text, float(self.settings["fuzz"]))
        entry = {"t": time.time(), "text": text, "source": source,
                 "lang": self.settings["stt_lang"], "score": round(sc, 2),
                 "id": None, "label": None, "target": None, "ran": False, "why": why}
        if cmd is not None:
            entry["id"] = cmd["id"]
            entry["label"] = cmd["label"]
            entry["target"] = cmd["target"]
            if not self.settings["listening"]:
                entry["ran"], entry["why"] = False, "not_listening"
            else:
                entry["ran"], entry["why"] = self._fire(cmd)
        self._log("voice_heard", text=text, source=source, score=entry["score"],
                  id=entry["id"], target=entry["target"], ran=entry["ran"],
                  why=entry["why"] or None)
        with self._lock:
            self.heard += 1
            self.transcript.append(entry)
        return entry

    def _fire(self, cmd):
        if not cmd["enabled"]:
            return False, "disabled"
        target = cmd["target"]
        if not target:
            return False, "no_target"
        now = time.monotonic()
        if now - self._last_fire.get(cmd["id"], -1e9) < config.VOICE_COOLDOWN_S:
            return False, "cooldown"
        if self.settings["dry_run"]:
            return False, "dry_run"
        self._last_fire[cmd["id"]] = now
        ok, note = self._dispatch(target)
        if ok:
            with self._lock:
                self.fired += 1
        return ok, note

    def _dispatch(self, target):
        if target.startswith("pose:"):
            if self.robot is None:
                return False, "no_robot"
            aid = int(target[5:])
            if self.robot.actions.get(aid) is None:
                return False, "no pose %d — check the command's target" % aid
            if getattr(self.robot, "estopped", False):
                return False, "E-STOPPED — press UNLOCK first"
            return (True, "") if self.robot.action_run(aid) else (False, "refused")
        if target.startswith("seq:"):
            if self.sequences is None:
                return False, "no_sequences"
            if self.robot is None:
                return False, "no_robot"
            sid = int(target[4:])
            if not any(s.get("id") == sid for s in self.sequences.public().get("seqs", [])):
                return False, "no sequence %d — check the command's target" % sid
            if getattr(self.robot, "estopped", False):
                return False, "E-STOPPED — press UNLOCK first"
            ok = self.sequences.start(sid, self.robot.get_state())
            return (True, "") if ok is not False else (False, "already running")
        if target in ("record_start", "record_stop", "record_toggle"):
            if self.recorder is None:
                return False, "no_recorder"
            fn = {"record_start": self.recorder.start,
                  "record_stop": self.recorder.stop,
                  "record_toggle": self.recorder.toggle}[target]
            ok, note = fn()
            return ok, ("" if ok else str(note)[:80])
        if self.robot is None:
            return False, "no_robot"
        fn = {"engage": self.robot.engage, "relax": self.robot.relax,
              "estop": self.robot.estop, "clear_estop": self.robot.clear_estop,
              "return_to_last": self.robot.return_to_last,
              "pose_record": self.robot.action_record}.get(target)
        if fn is None:
            return False, "unknown_target"
        return (True, "") if fn() else (False, "refused")

    def run_now(self, cid):
        cmd = self.commands.get(cid)
        if cmd is None:
            return None
        self._last_fire.pop(cmd["id"], None)
        ran, why = self._fire(cmd)
        entry = {"t": time.time(), "text": "", "source": "button",
                 "lang": self.settings["stt_lang"], "score": 1.0, "id": cmd["id"],
                 "label": cmd["label"], "target": cmd["target"],
                 "ran": ran, "why": why}
        self._log("voice_button", id=cmd["id"], target=cmd["target"], ran=ran,
                  why=why or None)
        with self._lock:
            self.transcript.append(entry)
        return entry

    def _log(self, kind, **f):
        if self.robot is not None and getattr(self.robot, "log", None) is not None:
            self.robot.log.cmd(kind, **f)

    def get_state(self):
        with self._lock:
            recent = list(self.transcript)[-40:]
        return {
            "mode": self.mode,
            "mic": self.mic.state(),
            "stt": self.stt.state(),
            "settings": self.settings.public(),
            "commands": self.commands.public(),
            "transcript": recent,
            "counts": {"heard": self.heard, "fired": self.fired},
            "hearing": bool(self.mic.speaking),
            "thinking": bool(self.thinking),
            "think_ms": int(max(0.0, time.time() - self.think_since) * 1000)
                        if self.thinking else 0,
            "last_ms": int(self.stt.last_ms or 0),
            "langs": list(config.LANGS),
            "lang_names": dict(config.LANG_NAMES),
        }

    def tail(self, n=200):
        with self._lock:
            return list(self.transcript)[-max(1, min(config.TRANSCRIPT_MAX, n)):]

    def shutdown(self):
        self._stop = True
        self.mic.stop()
        self._thread.join(timeout=2)
