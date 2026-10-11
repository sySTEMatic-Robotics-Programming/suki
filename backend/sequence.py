import json
import os
import time

from config import (SEQ_FILE, SEQ_HOLD_MAX, SEQ_MAX, SEQ_MAX_STEPS, SEQ_REPEAT_MAX,
                    SEQ_SEED, SEQ_SETTLE_US, SEQ_STEP_TIMEOUT_S)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _name(v, fallback):
    v = str(v or "").strip()[:48]
    return v or fallback


class SequenceStore:

    def __init__(self, path, write_json, actions):
        self.path = path
        self._write = write_json
        self.actions = actions
        self.seqs = []
        self._next_id = 1
        self._dirty = False
        self._seeded = []
        self.run = None
        self.note = None
        self._load()

    def _load(self):
        raw = None
        try:
            with open(self.path) as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = None
        if not isinstance(raw, dict) or not isinstance(raw.get("seqs"), list):
            self._seed()
            return
        seeded = raw.get("seeded")
        self._seeded = [str(x) for x in seeded] if isinstance(seeded, list) else []
        for s in raw["seqs"]:
            if isinstance(s, dict):
                self.seqs.append(self._make(s))
        if not seeded:
            self._seeded = [s["name"] for s in self.seqs]
            self.touch()
        self._seed()
        if not self.seqs:
            self._seeded = []
            self._seed()

    def _seed(self):
        by_name = {a["name"].strip().upper(): a["id"] for a in self.actions.actions}
        added = 0
        for s in SEQ_SEED:
            if s.get("name") in self._seeded:
                continue
            steps = [by_name[n.strip().upper()] for n in s.get("steps", [])
                     if n.strip().upper() in by_name]
            if len(steps) < 2:
                continue
            if len(self.seqs) >= SEQ_MAX:
                break
            self.seqs.append(self._make({
                "name": s.get("name"), "steps": steps, "hold": s.get("hold"),
                "reverse": s.get("reverse"), "repeat": s.get("repeat"),
            }))
            self._seeded.append(s.get("name"))
            added += 1
        if added:
            self.save()
            print("[suki] seeded %s with %d sequence(s)"
                  % (os.path.basename(self.path), added))

    def _make(self, raw):
        try:
            sid = int(raw.get("id"))
        except (TypeError, ValueError):
            sid = None
        if sid is None or sid < 1:
            sid = self._next_id
        self._next_id = max(self._next_id, sid + 1)
        steps, hold = [], None
        for st in (raw.get("steps") or [])[:SEQ_MAX_STEPS]:
            if isinstance(st, dict):
                if hold is None and st.get("hold") is not None:
                    hold = _num(st.get("hold"), 0.4)
                st = st.get("action")
            try:
                steps.append(int(st))
            except (TypeError, ValueError):
                continue
        if raw.get("hold") is not None:
            hold = _num(raw.get("hold"), 0.4)
        return {
            "id": sid,
            "name": _name(raw.get("name"), "sequence %d" % sid),
            "steps": steps,
            "hold": round(_clamp(0.4 if hold is None else hold, 0.0, SEQ_HOLD_MAX), 2),
            "reverse": bool(raw.get("reverse")),
            "repeat": int(_clamp(_num(raw.get("repeat"), 1), 1, SEQ_REPEAT_MAX)),
        }

    def save(self):
        self._write(self.path, {"seqs": self.seqs, "seeded": self._seeded})
        self._dirty = False

    def touch(self):
        self._dirty = True

    def flush(self):
        if not self._dirty:
            return
        try:
            self.save()
        except OSError as e:
            print("[seq] could not write %s: %s" % (self.path, e))
            self._dirty = False

    def get(self, sid):
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            return None
        for s in self.seqs:
            if s["id"] == sid:
                return s
        return None

    def _busy(self, sid=None):
        return bool(self.run) and (sid is None or self.run["seq"] == int(sid))

    def add(self, name=None):
        if len(self.seqs) >= SEQ_MAX:
            return None
        s = self._make({"name": name})
        self.seqs.append(s)
        self.touch()
        return s

    def rename(self, sid, name):
        s = self.get(sid)
        if s is None:
            return False
        s["name"] = _name(name, s["name"])
        self.touch()
        return True

    def set_opts(self, sid, reverse=None, repeat=None, hold=None):
        s = self.get(sid)
        if s is None or self._busy(sid):
            return False
        if reverse is not None:
            s["reverse"] = bool(reverse)
        if repeat is not None:
            s["repeat"] = int(_clamp(_num(repeat, 1), 1, SEQ_REPEAT_MAX))
        if hold is not None:
            s["hold"] = round(_clamp(_num(hold, 0.4), 0.0, SEQ_HOLD_MAX), 2)
        self.touch()
        return True

    def delete(self, sid):
        s = self.get(sid)
        if s is None or self._busy(sid):
            return False
        self.seqs.remove(s)
        self.touch()
        return True

    def add_step(self, sid, aid):
        s = self.get(sid)
        if s is None or self._busy(sid) or len(s["steps"]) >= SEQ_MAX_STEPS:
            return False
        if self.actions.get(aid) is None:
            return False
        s["steps"].append(int(aid))
        self.touch()
        return True

    def del_step(self, sid, index):
        s = self.get(sid)
        if s is None or self._busy(sid):
            return False
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        if not 0 <= index < len(s["steps"]):
            return False
        del s["steps"][index]
        self.touch()
        return True

    def _plan(self, s):
        fwd = list(s["steps"])
        if not fwd:
            return []
        rep = int(_clamp(s["repeat"], 1, SEQ_REPEAT_MAX))
        if not s["reverse"] or len(fwd) < 3:
            return fwd * rep
        lap = fwd + list(reversed(fwd[1:-1]))
        return lap * rep + [fwd[0]]

    def start(self, sid, state):
        if self.run:
            self.note = "already running"
            return False
        s = self.get(sid)
        if s is None:
            return False
        if state.get("estop"):
            self.note = "E-STOP is on"
            return False
        plan = self._plan(s)
        if len(plan) < 2:
            self.note = "needs at least two steps"
            return False
        if any(self.actions.get(aid) is None for aid in plan):
            self.note = "a step points at a pose that no longer exists"
            return False
        chans = set(state.get("action_channels") or [])
        if not any(r.get("enabled") for r in state.get("servos", [])
                   if r.get("ch") in chans):
            self.note = "every leg channel is switched off"
            return False
        self.run = {"seq": s["id"], "name": s["name"], "i": -1, "n": len(plan),
                    "plan": plan, "phase": "start", "started": time.time(),
                    "deadline": 0.0, "hold_until": 0.0,
                    "hold": float(s["hold"]),
                    "clipped": 0, "why": None, "noted": -1}
        self.note = None
        return True

    def stop(self, why="stopped"):
        if not self.run:
            return False
        self.note = "“%s” %s" % (self.run["name"], why)
        self.run = None
        return True

    def _settled(self, state):
        p = state.get("pulse") or {}
        if p.get("active") or p.get("pending"):
            return False
        chans = set(state.get("action_channels") or [])
        for r in state.get("servos", []):
            if r.get("ch") not in chans or not r.get("enabled"):
                continue
            if abs(int(r.get("us", 0)) - int(r.get("target", 0))) > SEQ_SETTLE_US:
                return False
        return True

    def tick(self, state, run_action):
        if not self.run:
            return
        now = time.time()
        r = self.run

        if state.get("estop"):
            self.stop("stopped by E-STOP")
            return

        if r["phase"] == "moving":
            if r["noted"] != r["i"]:
                r["noted"] = r["i"]
                why = state.get("action_note")
                if why:
                    r["clipped"] += 1
                    r["why"] = why
            if self._settled(state):
                r["phase"] = "holding"
                r["hold_until"] = now + r["hold"]
            elif now > r["deadline"]:
                self.stop("gave up: step %d did not arrive in %ds"
                          % (r["i"] + 1, int(SEQ_STEP_TIMEOUT_S)))
            return

        if r["phase"] == "holding" and now < r["hold_until"]:
            return

        r["i"] += 1
        if r["i"] >= r["n"]:
            self.stop("finished" if not r["clipped"] else
                      "finished — %d of %d step(s) were cut short by the corridor, so "
                      "the robot did not end up exactly where the poses say. %s"
                      % (r["clipped"], r["n"], r["why"] or ""))
            return
        if not run_action(r["plan"][r["i"]]):
            self.stop("the robot refused step %d" % (r["i"] + 1))
            return
        r["phase"] = "moving"
        r["deadline"] = now + SEQ_STEP_TIMEOUT_S

    def public(self):
        run = None
        if self.run:
            r = self.run
            aid = r["plan"][r["i"]] if 0 <= r["i"] < r["n"] else None
            a = self.actions.get(aid) if aid is not None else None
            run = {"seq": r["seq"], "name": r["name"],
                   "i": max(0, r["i"]), "n": r["n"], "phase": r["phase"],
                   "action": a["name"] if a else None,
                   "elapsed": round(time.time() - r["started"], 1)}
        return {
            "seqs": [{"id": s["id"], "name": s["name"], "reverse": s["reverse"],
                      "repeat": s["repeat"], "hold": s["hold"],
                      "steps": list(s["steps"]), "length": len(self._plan(s))}
                     for s in self.seqs],
            "run": run,
            "note": self.note,
            "max": SEQ_MAX, "max_steps": SEQ_MAX_STEPS,
            "hold_max": SEQ_HOLD_MAX, "repeat_max": SEQ_REPEAT_MAX,
        }


def demo():
    class FakeActions:
        def __init__(self):
            self.actions = [{"id": i, "name": n, "pos": {}}
                            for i, n in enumerate(["SIT DOWN", "P1", "P2", "P3"], 1)]

        def get(self, aid):
            try:
                aid = int(aid)
            except (TypeError, ValueError):
                return None
            return next((a for a in self.actions if a["id"] == aid), None)

    written = {}
    store = SequenceStore("/nonexistent/seq.json",
                          lambda p, d: written.__setitem__(p, d), FakeActions())
    store.seqs = []
    store._next_id = 1

    ran = []
    settled = {"v": True}
    pulsing = {"v": []}

    def state(estop=False, enabled=True):
        return {"estop": estop, "action_channels": [0, 1],
                "pulse": {"active": None, "pending": pulsing["v"]},
                "servos": [{"ch": 0, "enabled": enabled, "us": 1500,
                            "target": 1500 if settled["v"] else 2000},
                           {"ch": 1, "enabled": enabled, "us": 1500, "target": 1500}]}

    def run_action(aid):
        ran.append(aid)
        settled["v"] = False
        return True

    def pump(n=400, st=None):
        for _ in range(n):
            if not store.run:
                return
            store.tick(st or state(), run_action)
            if store.run and store.run["phase"] == "moving":
                settled["v"] = True
            if store.run and store.run["phase"] == "holding":
                store.run["hold_until"] = 0.0

    s = store.add(name="t")
    for aid in (1, 2, 3, 4):
        assert store.add_step(s["id"], aid)
    assert store._plan(s) == [1, 2, 3, 4], "plain order"
    store.set_opts(s["id"], reverse=True)
    assert store._plan(s) == [1, 2, 3, 4, 3, 2, 1], \
        "there and back ends where it started"
    store.set_opts(s["id"], repeat=2)
    assert store._plan(s) == [1, 2, 3, 4, 3, 2, 1, 2, 3, 4, 3, 2, 1], \
        "laps are seamless and end at home"
    store.set_opts(s["id"], repeat=1)

    ran.clear()
    assert store.start(s["id"], state()) is True
    pump()
    assert ran == [1, 2, 3, 4, 3, 2, 1], ran
    assert store.run is None and "finished" in store.note, store.note

    assert store.start(s["id"], state(estop=True)) is False and "E-STOP" in store.note
    assert store.start(s["id"], state(enabled=False)) is False
    assert "switched off" in store.note, store.note
    empty = store.add(name="empty")
    assert store.start(empty["id"], state()) is False
    assert "two steps" in store.note, store.note
    bad = store.add(name="bad")
    store.add_step(bad["id"], 1)
    store.add_step(bad["id"], 2)
    bad["steps"][1] = 999
    assert store.start(bad["id"], state()) is False
    assert "no longer exists" in store.note, store.note

    ran.clear()
    assert store.start(s["id"], state()) is True
    store.tick(state(), run_action)
    assert store.run is not None
    store.tick(state(estop=True), run_action)
    assert store.run is None and "E-STOP" in store.note, store.note

    ran.clear()
    assert store.start(s["id"], state()) is True
    store.tick(state(), run_action)
    store.run["deadline"] = time.time() - 1
    settled["v"] = False
    store.tick(state(), run_action)
    assert store.run is None and "did not arrive" in store.note, store.note

    old = store._make({"name": "old", "hold": None,
                       "steps": [{"action": 1, "hold": 1.25},
                                 {"action": 2, "hold": 1.25}]})
    assert old["steps"] == [1, 2], old["steps"]
    assert old["hold"] == 1.25, old["hold"]

    assert store.start(s["id"], state()) is True
    assert store.del_step(s["id"], 0) is False
    assert store.set_opts(s["id"], repeat=9) is False
    assert store.add_step(s["id"], 1) is False
    assert store.delete(s["id"]) is False
    assert store.start(s["id"], state()) is False and store.note == "already running"
    assert store.stop() is True and store.run is None

    n = len(ran)
    store.stop()
    assert len(ran) == n, "stop must not issue a pose"

    import tempfile
    path = os.path.join(tempfile.gettempdir(), "seq-selfcheck.json")
    disk = {}

    def to_disk(p, d):
        disk[p] = json.loads(json.dumps(d))

    class Loader(SequenceStore):

        def _load(self):
            raw = disk.get(self.path)
            if raw is None:
                self._seed()
                return
            seeded = raw.get("seeded")
            self._seeded = [str(x) for x in seeded] if isinstance(seeded, list) else []
            for s in raw["seqs"]:
                self.seqs.append(self._make(s))
            if not seeded:
                self._seeded = [x["name"] for x in self.seqs]
            self._seed()

    acts = FakeActions()
    acts.actions = [{"id": i, "name": n, "pos": {}} for i, n in
                    enumerate(["SIT DOWN", "P1", "P2", "P3", "P4"], 1)]
    names = lambda st: [x["name"] for x in st.seqs]

    a = Loader(path, to_disk, acts)
    first = names(a)
    assert len(first) == len([x for x in SEQ_SEED]), first
    a.flush()

    b = Loader(path, to_disk, acts)
    assert names(b) == first, names(b)

    b.delete(b.seqs[0]["id"])
    b.save()
    c = Loader(path, to_disk, acts)
    assert names(c) == first[1:], names(c)

    disk[path] = {"seqs": [{"id": 1, "name": first[0], "steps": [1, 2]}]}
    d = Loader(path, to_disk, acts)
    assert names(d).count(first[0]) == 1, names(d)

    assert set(names(d)) == set(first), names(d)

    ran.clear()
    settled["v"] = True
    pulsing["v"] = ["FR"]
    assert store.start(s["id"], state()) is True
    store.run["hold"] = 0.0
    store.tick(state(), run_action)
    for _ in range(20):
        store.tick(state(), run_action)
    assert ran == [1], "a pulsing leg must not advance the plan: %r" % ran
    pulsing["v"] = []
    settled["v"] = True
    store.tick(state(), run_action)
    settled["v"] = True
    store.tick(state(), run_action)
    assert ran == [1, 2], "arrival must advance it: %r" % ran
    store.stop()
    settled["v"] = True

    print("sequence.py self-check ok")


if __name__ == "__main__":
    demo()
