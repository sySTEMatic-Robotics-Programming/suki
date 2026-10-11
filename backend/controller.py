import json
import os
import threading
import time

import corridor as corr_mod
from actions import ActionStore
from config import (BUILD_TAG, CHANNELS, SERVOS, LEGS, THIGH, KNEE, HIP,
                    SERVO_DEFAULTS, CORRIDOR_SEED,
                    MIN_CORRIDOR_POINTS,
                    SAFE_MIN_US, SAFE_MAX_US,
                    TICK_HZ, DEFAULT_SPEED_US_PER_S, SPEED_MIN_US_PER_S,
                    SPEED_MAX_US_PER_S, PWM_REFRESH_S,
                    PCA_HEALTH_S, REJECT_LOG_S, SERVO_CONFIG_FILE, CORRIDOR_FILE,
                    STATE_FILE, ACTIONS_FILE, LOG_FILE, LOG_MAX_BYTES, LOG_PWM,
                    LOG_FLUSH_S, TICK_LATE_S, MOVE_ON_START, NEUTRAL_US,
                    MOTION_RT_PRIORITY,
                    DEFAULT_PULSE_US, PULSE_US_MAX, DEFAULT_PULSE_DELAY_MS,
                    PULSE_DELAY_MIN_MS, PULSE_DELAY_MAX_MS, PULSE_ARRIVE_TIMEOUT_S,
                    EDGE_WARN_US)
from driver import Pca9685, us_to_duty16
from log import Log

MIN_POINT_GAP_US = 5

_HERE = os.path.dirname(os.path.abspath(__file__))

AUTOSAVE_PERIOD_S = 2.0
AUTOSAVE_MIN_DELTA_US = 5


def _path(name):
    return os.path.join(_HERE, name)


def _write_json(path, data):
    tmp = "%s.%d.tmp" % (path, threading.get_ident())
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Controller:
    def __init__(self, force_sim=False):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.log = Log(_path(LOG_FILE), max_bytes=LOG_MAX_BYTES, pwm=LOG_PWM)
        self.log.info("boot", build=BUILD_TAG)

        self.min_us = {}
        self.max_us = {}
        self.invert = {}
        self.enabled = {}
        self.slots = {}
        self.slot_ch = {}
        self.names = {}
        self.speed_us_per_s = DEFAULT_SPEED_US_PER_S
        self._load_servo_config()

        self.corridors = {}
        self._load_corridor()

        self.actions = ActionStore(_path(ACTIONS_FILE), _write_json)
        self.action_note = None

        self.current_us = {ch: NEUTRAL_US for ch in CHANNELS}
        self.target_us = {ch: NEUTRAL_US for ch in CHANNELS}
        self.driven = {ch: False for ch in CHANNELS}
        self.estopped = False
        self.held_us = {ch: None for ch in CHANNELS}
        self.out_duty = {ch: 0 for ch in CHANNELS}
        self.rejects = {ch: 0 for ch in CHANNELS}
        self.last_reject = {ch: None for ch in CHANNELS}
        self._reject_log_at = {}
        self.leg_note = {leg: None for leg in LEGS}
        self.test_mode = False
        self.test_note = None

        self._restore_state()

        self.pca = Pca9685(force_sim=force_sim or bool(os.environ.get("SUKI_FORCE_SIM")))
        self.pca.log = self.log
        for ch in range(16):
            self.pca.set_duty(ch, 0)
        try:
            self.pca.flush()
        except Exception as e:
            self.pca.note_error(e)

        if MOVE_ON_START:
            for ch in CHANNELS:
                if self.enabled.get(ch):
                    self.driven[ch] = True

        self.boot_pose = dict(self.current_us)

        self._verify_i = 0
        self._state_dirty = False
        self._corridor_dirty = False
        self.tick_hz = float(TICK_HZ)
        self.ticks_late = 0
        self.rt = False
        self._last_tick = 0.0
        self._at_edge = set()

        pu, pd = getattr(self, "_pulse_from_file", (None, None))
        try:
            self.pulse_us = max(0, min(PULSE_US_MAX,
                                       int(DEFAULT_PULSE_US if pu is None else pu)))
        except (TypeError, ValueError):
            self.pulse_us = DEFAULT_PULSE_US
        try:
            self.pulse_delay_s = max(PULSE_DELAY_MIN_MS, min(
                PULSE_DELAY_MAX_MS,
                int(DEFAULT_PULSE_DELAY_MS if pd is None else pd))) / 1000.0
        except (TypeError, ValueError):
            self.pulse_delay_s = DEFAULT_PULSE_DELAY_MS / 1000.0
        self.goal = {leg: None for leg in LEGS}
        self._pulse_leg = None
        self._pulse_done = None
        self._pulse_at = 0.0
        self._pulse_deadline = 0.0
        self._pulse_i = 0
        self._saved_pose = dict(self.current_us)
        self._save_at = 0.0
        print("[suki] build %s, %s mode" % (BUILD_TAG, self.pca.mode))

        self._thread = threading.Thread(target=self._run, name="motion", daemon=True)
        self._thread.start()
        self._saver = threading.Thread(target=self._saver_run, name="saver",
                                       daemon=True)
        self._saver.start()

    def _load_map(self, saved):
        labels = {(leg, joint): lbl for leg, joint, lbl in SERVOS.values()}
        where = None
        if isinstance(saved, dict):
            try:
                got = {int(k): (str(v[0]), str(v[1])) for k, v in saved.items()}
            except (TypeError, ValueError, IndexError, KeyError):
                got = None
            if got is not None and (
                    all(c in CHANNELS for c in got)
                    and sorted(got.values()) == sorted(labels)):
                where = {jt: ch for ch, jt in got.items()}
            elif got is not None:
                print("[suki] the saved channel map does not place every joint exactly "
                      "once - falling back to the built-in one")
        if where is None:
            where = {(leg, joint): ch for ch, (leg, joint, _l) in SERVOS.items()}
        self.slots = {ch: None for ch in CHANNELS}
        for (leg, joint), ch in where.items():
            self.slots[ch] = (leg, joint, labels[(leg, joint)])
        self._rebuild_map()

    def _rebuild_map(self):
        self.slot_ch = {(s[0], s[1]): ch for ch, s in self.slots.items() if s}
        self.names = {ch: (self.slots[ch][2] if self.slots[ch] else "— unused —")
                      for ch in CHANNELS}

    def _slot(self, ch):
        return self.slots.get(ch)

    def _ch(self, leg, joint):
        return self.slot_ch.get((leg, joint))

    def _joint_order(self):
        return [self._ch(leg, joint) for leg, joint, _l in
                (SERVOS[c] for c in sorted(SERVOS))]

    def _action_channels(self):
        return [ch for ch in CHANNELS
                if self.slots.get(ch) and self.slots[ch][1] != HIP]

    def _load_servo_config(self):
        raw = _read_json(_path(SERVO_CONFIG_FILE))
        fresh = raw is None
        raw = raw or {}
        self._load_map(raw.get("map") if isinstance(raw, dict) else None)
        cfg = raw.get("servos", raw) if isinstance(raw, dict) else {}
        for ch in CHANNELS:
            d = dict(SERVO_DEFAULTS.get(ch, {
                "min": SAFE_MIN_US, "max": SAFE_MAX_US, "invert": False,
                "enabled": self.slots.get(ch) is not None}))
            saved = cfg.get(str(ch)) if isinstance(cfg, dict) else None
            if isinstance(saved, dict):
                d.update({k: saved[k] for k in ("min", "max", "invert", "enabled")
                          if k in saved})
            lo = max(SAFE_MIN_US, min(SAFE_MAX_US, int(d["min"])))
            hi = max(SAFE_MIN_US, min(SAFE_MAX_US, int(d["max"])))
            if hi < lo:
                lo, hi = hi, lo
            self.min_us[ch] = lo
            self.max_us[ch] = hi
            self.invert[ch] = bool(d["invert"])
            self.enabled[ch] = bool(d["enabled"])
        if isinstance(raw, dict) and "speed_us_per_s" in raw:
            self.speed_us_per_s = self._clamp_speed(raw["speed_us_per_s"])
        self._pulse_from_file = (raw.get("pulse_us") if isinstance(raw, dict) else None,
                                 raw.get("pulse_delay_ms") if isinstance(raw, dict)
                                 else None)
        if fresh:
            self._save_servo_config()
            print("[suki] seeded %s from the built-in calibration" % SERVO_CONFIG_FILE)

    def _save_servo_config(self):
        _write_json(_path(SERVO_CONFIG_FILE), {
            "speed_us_per_s": int(self.speed_us_per_s),
            "pulse_us": int(self.pulse_us),
            "pulse_delay_ms": int(self.pulse_delay_s * 1000),
            "map": {str(ch): [s[0], s[1]] for ch, s in self.slots.items() if s},
            "servos": {str(ch): {"name": self.names[ch],
                                 "min": int(self.min_us[ch]),
                                 "max": int(self.max_us[ch]),
                                 "invert": bool(self.invert[ch]),
                                 "enabled": bool(self.enabled[ch])}
                       for ch in CHANNELS},
        })

    def _load_corridor(self):
        raw = _read_json(_path(CORRIDOR_FILE))
        if not isinstance(raw, dict) or not raw:
            raw = {leg: {"points": [dict(p) for p in pts]}
                   for leg, pts in CORRIDOR_SEED.items()}
            _write_json(_path(CORRIDOR_FILE), raw)
            print("[suki] seeded %s with the measured corridors" % CORRIDOR_FILE)
        for leg in LEGS:
            entry = raw.get(leg) or {}
            pts = entry.get("points") if isinstance(entry, dict) else entry
            self.corridors[leg] = corr_mod.Corridor(pts or [])
            if not self.corridors[leg].ok:
                print("[suki] %s has no usable corridor - that leg is NOT drivable"
                      % leg)

    def _save_corridor(self):
        _write_json(_path(CORRIDOR_FILE),
                    {leg: {"points": self.corridors[leg].points()} for leg in LEGS})

    def _restore_state(self):
        saved = _read_json(_path(STATE_FILE)) or {}
        pos = saved.get("pos", saved) if isinstance(saved, dict) else {}
        for ch in CHANNELS:
            v = pos.get(str(ch)) if isinstance(pos, dict) else None
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = NEUTRAL_US
            lo, hi = self._static_bounds(ch)
            self.current_us[ch] = self.target_us[ch] = max(lo, min(hi, v))
        for leg in LEGS:
            c = self.corridors.get(leg)
            dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
            if not c or not c.ok or dch is None or pch is None:
                continue
            t = int(round(c.clamp_thigh(self.current_us[dch])))
            k = int(round(c.clamp_knee(t, self.current_us[pch])))
            self.current_us[dch] = self.target_us[dch] = t
            self.current_us[pch] = self.target_us[pch] = k

    def _save_state(self):
        _write_json(_path(STATE_FILE),
                    {"pos": {str(ch): int(self.current_us[ch]) for ch in CHANNELS}})

    def _static_bounds(self, ch):
        return (max(SAFE_MIN_US, int(self.min_us[ch])),
                min(SAFE_MAX_US, int(self.max_us[ch])))

    def _travel_bounds(self, ch):
        if self.test_mode:
            return SAFE_MIN_US, SAFE_MAX_US
        return self._static_bounds(ch)

    def _map_span(self, ch):
        if self.test_mode:
            return SAFE_MIN_US + SAFE_MAX_US
        return self.min_us[ch] + self.max_us[ch]

    def _corridor_bounds(self, ch):
        if self.test_mode:
            return None
        s = self._slot(ch)
        if s is None:
            return None
        leg, joint, _lbl = s
        c = self.corridors.get(leg)
        if c is None or not c.ok:
            return None
        if joint == THIGH:
            return c.thigh_span()
        if joint == KNEE:
            dch = self._ch(leg, THIGH)
            if dch is None:
                return None
            return c.window(self.current_us[dch])
        return None

    def _pulse_limits(self, ch):
        lo, hi = self._travel_bounds(ch)
        c = self._corridor_bounds(ch)
        if c is not None:
            lo, hi = max(lo, int(round(c[0]))), min(hi, int(round(c[1])))
        held = self.held_us.get(ch)
        if held is not None:
            lo, hi = min(lo, int(held)), max(hi, int(held))
        if hi < lo:
            lo, hi = hi, lo
        return lo, hi

    def _drivable_bounds(self, ch):
        lo, hi = self._travel_bounds(ch)
        c = self._corridor_bounds(ch)
        if c is not None:
            lo, hi = max(lo, int(round(c[0]))), min(hi, int(round(c[1])))
        if hi < lo:
            lo, hi = hi, lo
        return lo, hi

    def physical_us(self, ch, us=None):
        us = self.current_us[ch] if us is None else us
        if self.invert.get(ch):
            return self._map_span(ch) - int(us)
        return int(us)

    def _edge_report(self, ch):
        lo, hi = self._drivable_bounds(ch)
        p_now = self.physical_us(ch)
        p_ends = (self.physical_us(ch, lo), self.physical_us(ch, hi))
        def near(p):
            return p <= SAFE_MIN_US + EDGE_WARN_US or p >= SAFE_MAX_US - EDGE_WARN_US
        if self.test_mode:
            return near(p_now), False
        return near(p_now), any(near(p) for p in p_ends)

    def _note_edges_locked(self):
        for ch in CHANNELS:
            if not self._energised(ch):
                self._at_edge.discard(ch)
                continue
            now_edge, _span = self._edge_report(ch)
            if now_edge and ch not in self._at_edge:
                self._at_edge.add(ch)
                p = int(self.physical_us(ch))
                self.log.err(
                    "at_end_stop", ch=ch, name=self.names.get(ch),
                    us=int(self.current_us[ch]), phys=p,
                    min=int(self.min_us[ch]), max=int(self.max_us[ch]),
                    fix=("raise min above %d" % self.min_us[ch]) if p < 1500
                        else ("lower max below %d" % self.max_us[ch]),
                    why="the servo is being pushed against its mechanical stop - it "
                        "will stall, heat and sag the rail, and the joint will not move")
            elif not now_edge:
                self._at_edge.discard(ch)

    def _clamp_speed(self, v):
        try:
            v = int(float(v))
        except (TypeError, ValueError):
            return self.speed_us_per_s
        return max(SPEED_MIN_US_PER_S, min(SPEED_MAX_US_PER_S, v))

    def _energised(self, ch) -> bool:
        return bool(self.enabled.get(ch) and self.driven.get(ch)
                    and not self.estopped and self.pca.drivable)

    def _write(self, ch, us) -> bool:
        if ch not in self.min_us:
            return False
        try:
            us = int(round(float(us)))
        except (TypeError, ValueError):
            self._reject(ch, "position is not a number")
            return False
        if not self._energised(ch):
            self._write_off(ch)
            return False

        lo, hi = self._pulse_limits(ch)
        if us < lo or us > hi:
            held = self.held_us.get(ch)
            if held is not None and lo <= held <= hi:
                self._reject(ch, "%dus is outside %d..%d - NOT executed, %dus stays "
                                 "on the wire" % (us, lo, hi, held))
                return False
            self._reject(ch, "%dus is outside %d..%d - driving to the limit instead "
                             "(nothing legal has been sent to this joint yet)"
                        % (us, lo, hi))
            us = max(lo, min(hi, us))

        phys = self.physical_us(ch, us)
        if phys < SAFE_MIN_US or phys > SAFE_MAX_US:
            self._reject(ch, "would put %dus on the wire, outside the servo's %d..%dus "
                             "datasheet range - check min/max/invert"
                        % (phys, SAFE_MIN_US, SAFE_MAX_US))
            return False

        duty = us_to_duty16(phys)
        self.held_us[ch] = us
        self.out_duty[ch] = duty
        if self.pca.staged(ch) != duty:
            self.pca.set_duty(ch, duty)
            self.log.pwm(ch=ch, us=us, phys=phys, duty=duty)
        return True

    def _write_off(self, ch):
        self.out_duty[ch] = 0
        if self.pca.staged(ch) != 0:
            self.pca.set_duty(ch, 0)

    def _reject(self, ch, reason):
        self.rejects[ch] = self.rejects.get(ch, 0) + 1
        self.last_reject[ch] = reason
        self.log.err("reject", ch=ch, name=self.names.get(ch), why=reason)
        now = time.monotonic()
        if now - self._reject_log_at.get(ch, -1e9) >= REJECT_LOG_S:
            self._reject_log_at[ch] = now
            print("[suki] REFUSED %s (ch%d): %s" % (self.names.get(ch), ch, reason))

    def _run(self):
        self._ask_for_realtime()
        dt = 1.0 / TICK_HZ
        now = time.monotonic()
        next_refresh = now + PWM_REFRESH_S
        next_health = now + PCA_HEALTH_S
        next_tick = now + dt
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                beat = now >= next_refresh
                if beat:
                    next_refresh = now + PWM_REFRESH_S
                if now >= next_health:
                    next_health = now + PCA_HEALTH_S
                    self.pca.health_check()
                self._tick(dt, beat)
            except Exception as e:
                self.pca.note_error(e)

            next_tick += dt
            slack = next_tick - time.monotonic()
            if slack > 0:
                time.sleep(slack)
            else:
                self.ticks_late += 1
                if -slack > TICK_LATE_S:
                    self.log.err("slow_tick", late_ms=round(-slack * 1000, 1))
                next_tick = time.monotonic()
            n = time.monotonic()
            if self._last_tick:
                self.tick_hz = 0.9 * self.tick_hz + 0.1 / max(1e-6, n - self._last_tick)
            self._last_tick = n

    def _ask_for_realtime(self):
        try:
            os.sched_setscheduler(0, os.SCHED_FIFO,
                                  os.sched_param(MOTION_RT_PRIORITY))
        except (AttributeError, OSError, ValueError) as e:
            self.log.info("motion_priority", realtime=False, why=str(e)[:80])
            print("[suki] motion thread is on the normal scheduler (%s). Ticks will be "
                  "late when vision or whisper is busy; see HARDWARE.md for how to "
                  "grant CAP_SYS_NICE." % e.__class__.__name__)
            return
        self.rt = True
        self.log.info("motion_priority", realtime=True, prio=MOTION_RT_PRIORITY)
        print("[suki] motion thread running SCHED_FIFO:%d" % MOTION_RT_PRIORITY)

    def _settle_idle_locked(self):
        for leg in LEGS:
            dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
            c = self.corridors.get(leg)
            if dch is None or pch is None or c is None or not c.ok:
                continue
            if self._energised(dch) or self._energised(pch):
                continue
            t = int(round(c.clamp_thigh(self.current_us[dch])))
            k = int(round(c.clamp_knee(t, self.current_us[pch])))
            if t != self.current_us[dch] or k != self.current_us[pch]:
                self.log.info("settled", leg=leg,
                              was=[self.current_us[dch], self.current_us[pch]],
                              now=[t, k])
                self.current_us[dch] = self.target_us[dch] = t
                self.current_us[pch] = self.target_us[pch] = k
        for ch in CHANNELS:
            s = self._slot(ch)
            if s is None or s[1] != HIP or self._energised(ch):
                continue
            lo, hi = self._static_bounds(ch)
            v = max(lo, min(hi, self.current_us[ch]))
            if v != self.current_us[ch]:
                self.current_us[ch] = self.target_us[ch] = v

    def _goal_pending(self, leg):
        g = self.goal.get(leg)
        if not g:
            return False
        dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
        if dch is None or pch is None or not self._energised(dch):
            return False
        return (self.current_us[dch] != g[0] or self.current_us[pch] != g[1])

    def _arrived(self, leg):
        dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
        return (abs(self.current_us[dch] - self.target_us[dch]) <= 1 and
                abs(self.current_us[pch] - self.target_us[pch]) <= 1)

    def _pulse_tick_locked(self, now):
        if self.pulse_us <= 0:
            return
        if self._pulse_leg is not None:
            leg = self._pulse_leg
            if not self._arrived(leg) and now < self._pulse_deadline:
                return
            if now >= self._pulse_deadline and not self._arrived(leg):
                self.log.err("pulse_timeout", leg=leg,
                             at=[self.current_us[self._ch(leg, THIGH)],
                                 self.current_us[self._ch(leg, KNEE)]])
                self.goal[leg] = None
            self._pulse_leg = None
            self._pulse_done = leg
            self._pulse_at = now
        pending = [leg for leg in LEGS if self._goal_pending(leg)]
        for leg in LEGS:
            if self.goal.get(leg) and leg not in pending:
                self.goal[leg] = None
        if not pending:
            return

        if len(pending) == 1:
            leg, step = pending[0], None
        else:
            order = LEGS
            start = self._pulse_i % len(order)
            leg = next(order[(start + i) % len(order)] for i in range(len(order))
                       if order[(start + i) % len(order)] in pending)
            step = True

        if leg != self._pulse_done and now < self._pulse_at + self.pulse_delay_s:
            return
        if step is not None:
            self._pulse_i = (LEGS.index(leg) + 1) % len(LEGS)
        self._issue_pulse_locked(leg, now, step=step)

    def _issue_pulse_locked(self, leg, now, step=True):
        if step is True:
            step = self.pulse_us
        c = self.corridors.get(leg)
        dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
        t0, k0 = self.current_us[dch], self.current_us[pch]
        gt, gk = self.goal[leg]
        far = max(abs(gt - t0), abs(gk - k0))
        u = 1.0 if (step is None or far <= step) else float(step) / far
        wt, wk = t0 + (gt - t0) * u, k0 + (gk - k0) * u
        t, k, clipped, why = corr_mod.reach(c, t0, k0, wt, wk)
        if (t, k) == (t0, k0):
            self.goal[leg] = None
            self.leg_note[leg] = why or self.leg_note.get(leg)
            self.log.err("pulse_blocked", leg=leg, at=[t0, k0], goal=[gt, gk], why=why)
            return
        self._aim(dch, t)
        self._aim(pch, k)
        self._pulse_leg = leg
        travel = max(abs(t - t0), abs(k - k0))
        self._pulse_deadline = now + max(
            PULSE_ARRIVE_TIMEOUT_S,
            2.0 * travel / max(1.0, float(self.speed_us_per_s)) + 0.5)
        self.log.info("pulse", leg=leg, frm=[t0, k0], to=[t, k], goal=[gt, gk],
                      step=step)

    def _tick(self, dt, beat):
        with self._lock:
            step = self.speed_us_per_s * dt
            coupled = set()

            if not self.estopped:
                if not self.test_mode:
                    self._settle_idle_locked()
                    self._pulse_tick_locked(time.monotonic())
                    for leg in LEGS:
                        dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
                        c = self.corridors.get(leg)
                        if dch is None or pch is None or c is None or not c.ok:
                            continue
                        self._advance_leg(leg, c, dch, pch, step)
                        coupled.update((dch, pch))
                self._note_edges_locked()

                for ch in CHANNELS:
                    if ch in coupled:
                        continue
                    if self._energised(ch):
                        lo, hi = self._drivable_bounds(ch)
                        tgt = max(lo, min(hi, self.target_us[ch]))
                        cur = self.current_us[ch]
                        if cur != tgt:
                            d = tgt - cur
                            cur = tgt if abs(d) <= step else cur + (step if d > 0 else -step)
                            self.current_us[ch] = int(round(cur))

            for ch in CHANNELS:
                if self._energised(ch):
                    self._write(ch, self.current_us[ch])
                else:
                    self._write_off(ch)

            if beat:
                for ch in CHANNELS:
                    self.pca.set_duty(ch, self.out_duty.get(ch, 0))

            try:
                self.pca.flush()
                if beat:
                    self._verify_i = (self._verify_i + 1) % len(CHANNELS)
                    vch = CHANNELS[self._verify_i]
                    self.pca.verify(vch, self.out_duty.get(vch, 0))
            except Exception as e:
                self.pca.note_error(e)

    def _advance_leg(self, leg, c, dch, pch, step):
        thigh_on = self._energised(dch)
        knee_on = self._energised(pch)
        if not thigh_on and not knee_on:
            return
        t0, k0 = self.current_us[dch], self.current_us[pch]

        if not thigh_on:
            w = c.window(t0)
            kt = max(w[0], min(w[1], float(self.target_us[pch])))
            self.current_us[pch] = int(round(k0 + max(-step, min(step, kt - k0))))
            return

        t, k = corr_mod.step(c, t0, k0, self.target_us[dch], self.target_us[pch],
                             step, knee_follows=knee_on)
        self.current_us[dch] = t
        if knee_on:
            self.current_us[pch] = k

    def _saver_run(self):
        while not self._stop.wait(0.1):
            try:
                self._autosave()
                self.log.flush()
            except Exception as e:
                print("[suki] saver: %s" % e)

    def _autosave(self):
        now = time.monotonic()
        if now < self._save_at:
            return
        self._save_at = now + AUTOSAVE_PERIOD_S
        if self._corridor_dirty:
            self._corridor_dirty = False
            with self._lock:
                rows = {leg: {"points": self.corridors[leg].points()} for leg in LEGS}
            try:
                _write_json(_path(CORRIDOR_FILE), rows)
            except OSError as e:
                print("[suki] could not save the corridor: %s" % e)
        with self._lock:
            pose = dict(self.current_us)
        if not self._state_dirty and all(
                abs(pose[ch] - self._saved_pose.get(ch, -9999)) < AUTOSAVE_MIN_DELTA_US
                for ch in CHANNELS):
            return
        self._state_dirty = False
        self._saved_pose = pose
        try:
            _write_json(_path(STATE_FILE),
                        {"pos": {str(ch): int(v) for ch, v in pose.items()}})
        except OSError as e:
            print("[suki] could not save state: %s" % e)

    def _aim(self, ch, us):
        lo, hi = self._travel_bounds(ch)
        self.target_us[ch] = int(max(lo, min(hi, int(round(float(us))))))

    def set_leg_pair(self, leg, thigh_us=None, knee_us=None):
        if leg not in LEGS:
            return False
        c = self.corridors.get(leg)
        dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
        if c is None or not c.ok or dch is None or pch is None:
            return False
        with self._lock:
            if self.estopped:
                return False
            if self.test_mode:
                self.leg_note[leg] = ("the hardware test is armed — stop it to move "
                                      "this leg from the chart or the sliders")
                return False
            if not (self._energised(dch) or self._energised(pch)):
                self.leg_note[leg] = ("this leg is limp — press Engage, or Return to "
                                      "last position, before moving it")
                return False
            t_want = self.current_us[dch] if thigh_us is None else float(thigh_us)
            k_want = self.current_us[pch] if knee_us is None else float(knee_us)
            t, k, clipped, why = corr_mod.reach(c, self.current_us[dch],
                                                self.current_us[pch], t_want, k_want)
            self.leg_note[leg] = why if clipped else None
            self._set_destination_locked(leg, t, k)
            self._state_dirty = True
        return True

    def _set_destination_locked(self, leg, t, k):
        dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
        if self.pulse_us > 0:
            self.goal[leg] = (int(t), int(k))
        else:
            self.goal[leg] = None
            self._aim(dch, t)
            self._aim(pch, k)

    def set_servo(self, ch, us):
        try:
            ch = int(ch)
        except (TypeError, ValueError):
            return False
        if ch not in self.min_us:
            return False
        s = self._slot(ch)
        if s is None:
            return False
        leg, joint, _lbl = s
        if joint == THIGH:
            return self.set_leg_pair(leg, thigh_us=us)
        if joint == KNEE:
            return self.set_leg_pair(leg, knee_us=us)
        with self._lock:
            if self.estopped or self.test_mode or not self._energised(ch):
                return False
            lo, hi = self._drivable_bounds(ch)
            self.target_us[ch] = int(max(lo, min(hi, int(round(float(us))))))
            self._state_dirty = True
        return True

    def _remap_locked(self, ch, old_span, new_span):
        if old_span == new_span or not self.invert.get(ch):
            return
        d = int(new_span) - int(old_span)
        for m in (self.current_us, self.target_us):
            m[ch] = int(m[ch]) + d
        if self.held_us[ch] is not None:
            self.held_us[ch] = int(self.held_us[ch]) + d

    def set_servo_config(self, ch, invert=None, enabled=None, min_us=None, max_us=None):
        try:
            ch = int(ch)
        except (TypeError, ValueError):
            return False
        if ch not in self.min_us:
            return False
        with self._lock:
            s = self._slot(ch)
            leg, joint = (s[0], s[1]) if s else (None, None)
            if min_us is not None or max_us is not None:
                lo = int(self.min_us[ch] if min_us is None else min_us)
                hi = int(self.max_us[ch] if max_us is None else max_us)
                lo = max(SAFE_MIN_US, min(SAFE_MAX_US, lo))
                hi = max(SAFE_MIN_US, min(SAFE_MAX_US, hi))
                if hi < lo:
                    lo, hi = hi, lo
                phys = int(self.physical_us(ch))
                old_span = self._map_span(ch)
                self.min_us[ch], self.max_us[ch] = lo, hi
                self._remap_locked(ch, old_span, self._map_span(ch))
                self.log.cmd("servo_range", ch=ch, min=lo, max=hi, phys_held=phys)
            if enabled is not None:
                self.enabled[ch] = bool(enabled)
                if not self.enabled[ch]:
                    self.driven[ch] = False
                elif self.test_mode:
                    self.target_us[ch] = self.current_us[ch]
                    self.driven[ch] = True
            if invert is not None and bool(invert) != bool(self.invert[ch]):
                live = self._map_span(ch)
                self.invert[ch] = bool(invert)
                for d in (self.current_us, self.target_us):
                    d[ch] = int(live - d[ch])
                if self.held_us[ch] is not None:
                    self.held_us[ch] = int(live - self.held_us[ch])
                self._mirror_corridor(leg, joint, self.min_us[ch] + self.max_us[ch])
            self._save_servo_config()
            self._save_corridor()
        return True

    def set_channel_slot(self, ch, leg, joint):
        try:
            ch = int(ch)
        except (TypeError, ValueError):
            return False
        want = (str(leg), str(joint))
        if ch not in self.slots or want not in self.slot_ch:
            return False
        with self._lock:
            was = self.slot_ch[want]
            if was == ch:
                return True
            self.relax()
            for m in (self.min_us, self.max_us, self.invert, self.enabled,
                      self.current_us, self.target_us, self.held_us, self.out_duty,
                      self.rejects, self.last_reject, self.slots):
                m[ch], m[was] = m[was], m[ch]
            self._rebuild_map()
            self._at_edge.discard(ch)
            self._at_edge.discard(was)
            for l in LEGS:
                self.leg_note[l] = None
            self.actions.swap_channels(ch, was)
            self._save_servo_config()
            self._state_dirty = True
        self.log.cmd("channel_map", ch=ch, swapped_with=was,
                     now={str(ch): self.names[ch], str(was): self.names[was]})
        print("[suki] channel map: ch%d <-> ch%d (%s / %s) - everything relaxed"
              % (ch, was, self.names[ch], self.names[was]))
        return True

    def set_test_mode(self, on):
        on = bool(on)
        with self._lock:
            if on == self.test_mode:
                return True
            if on and self.estopped:
                return False
            old = {ch: self._map_span(ch) for ch in CHANNELS}
            self.test_mode = on
            for ch in CHANNELS:
                self._remap_locked(ch, old[ch], self._map_span(ch))
            self._drop_goals()
            for leg in LEGS:
                self.leg_note[leg] = None
            if on:
                for ch in CHANNELS:
                    if self.enabled.get(ch):
                        self.target_us[ch] = self.current_us[ch]
                        self.driven[ch] = True
                self.test_note = None
            else:
                self.test_note = self._leave_test_locked()
        self.log.cmd("test_mode", on=on, note=self.test_note)
        print("[suki] hardware test %s" % ("ARMED - raw 500..2500us, no corridor"
                                           if on else "stopped"))
        return True

    def _leave_test_locked(self):
        loose = []
        for leg in LEGS:
            dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
            c = self.corridors.get(leg)
            if dch is None or pch is None or c is None or not c.ok:
                continue
            if c.contains(self.current_us[dch], self.current_us[pch]):
                continue
            for ch in (dch, pch):
                self.driven[ch] = False
            self.leg_note[leg] = ("the hardware test left this leg outside its measured "
                                  "corridor, so it has been made limp — move it back by "
                                  "hand, or press Engage to hold it where it is")
            loose.append(leg)
        if not loose:
            return None
        self.log.err("test_left_outside", legs=loose)
        return ("stopped — %s ended up outside the measured corridor and %s been left "
                "limp rather than driven back into it"
                % (", ".join(loose), "has" if len(loose) == 1 else "have"))

    def set_test_us(self, ch, us):
        try:
            ch = int(ch)
        except (TypeError, ValueError):
            return False
        if ch not in self.min_us:
            return False
        with self._lock:
            if not self.test_mode or self.estopped:
                return False
            if not self._energised(ch):
                self.test_note = (
                    "%s did not move: it is switched off. Tick its “on” box."
                    % self.names.get(ch, "ch%d" % ch)) if not self.enabled.get(ch) else (
                    "%s did not move: the driver is not able to hold it right now."
                    % self.names.get(ch, "ch%d" % ch))
                return False
            lo, hi = self._travel_bounds(ch)
            try:
                self.target_us[ch] = int(max(lo, min(hi, round(float(us)))))
            except (TypeError, ValueError):
                return False
            self._state_dirty = True
        return True

    def set_corridor_point(self, leg, index, drive=None, min_us=None, max_us=None):
        if leg not in LEGS:
            return False
        c = self.corridors.get(leg)
        if c is None or not c.rows:
            return False
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        rows = [dict(p) for p in c.points()]
        if not (0 <= index < len(rows)):
            return False
        dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
        with self._lock:
            row = rows[index]
            if drive is not None and dch is not None:
                lo, hi = self._static_bounds(dch)
                if index > 0:
                    lo = max(lo, rows[index - 1]["drive"] + MIN_POINT_GAP_US)
                if index < len(rows) - 1:
                    hi = min(hi, rows[index + 1]["drive"] - MIN_POINT_GAP_US)
                if hi >= lo:
                    row["drive"] = int(max(lo, min(hi, round(float(drive)))))
            if pch is not None and (min_us is not None or max_us is not None):
                klo, khi = self._static_bounds(pch)
                if min_us is not None:
                    row["min"] = int(max(klo, min(khi, round(float(min_us)))))
                if max_us is not None:
                    row["max"] = int(max(klo, min(khi, round(float(max_us)))))
                if row["min"] > row["max"]:
                    row["min"], row["max"] = row["max"], row["min"]
            new = corr_mod.Corridor(rows)
            if not new.ok:
                return False
            self.corridors[leg] = new
            self._corridor_dirty = True
        self.log.cmd("corridor_point", leg=leg, index=index, row=row)
        return True

    def add_corridor_point(self, leg, drive):
        if leg not in LEGS:
            return False
        c = self.corridors.get(leg)
        if c is None or not c.ok:
            return False
        dch = self._ch(leg, THIGH)
        with self._lock:
            lo, hi = self._static_bounds(dch)
            try:
                d = int(max(lo, min(hi, round(float(drive)))))
            except (TypeError, ValueError):
                return False
            rows = [dict(p) for p in c.points()]
            if any(abs(r["drive"] - d) < MIN_POINT_GAP_US for r in rows):
                return False
            w = c.window(d)
            rows.append({"drive": d, "min": int(round(w[0])), "max": int(round(w[1]))})
            new = corr_mod.Corridor(rows)
            if not new.ok:
                return False
            self.corridors[leg] = new
            self._corridor_dirty = True
        self.log.cmd("corridor_add", leg=leg, drive=d, window=[int(w[0]), int(w[1])])
        return True

    def delete_corridor_point(self, leg, index):
        if leg not in LEGS:
            return False
        c = self.corridors.get(leg)
        if c is None or not c.ok:
            return False
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        rows = [dict(p) for p in c.points()]
        if not (0 <= index < len(rows)) or len(rows) <= MIN_CORRIDOR_POINTS:
            return False
        gone = rows.pop(index)
        with self._lock:
            new = corr_mod.Corridor(rows)
            if not new.ok:
                return False
            self.corridors[leg] = new
            self._corridor_dirty = True
        self.log.cmd("corridor_delete", leg=leg, index=index, row=gone)
        return True

    def _mirror_corridor(self, leg, joint, span):
        c = self.corridors.get(leg)
        if c is None or not c.rows:
            return
        rows = []
        for d, lo, hi in c.rows:
            if joint == THIGH:
                rows.append({"drive": span - d, "min": lo, "max": hi})
            elif joint == KNEE:
                rows.append({"drive": d, "min": span - hi, "max": span - lo})
            else:
                return
        self.corridors[leg] = corr_mod.Corridor(rows)

    def return_to_last(self):
        with self._lock:
            if self.estopped:
                return False
            pose = dict(self.boot_pose)
        self.engage()
        notes = []
        with self._lock:
            for leg in LEGS:
                dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
                c = self.corridors.get(leg)
                if dch is None or pch is None or c is None or not c.ok:
                    continue
                t, k, clipped, why = corr_mod.reach(
                    c, self.current_us[dch], self.current_us[pch],
                    pose.get(dch, self.current_us[dch]),
                    pose.get(pch, self.current_us[pch]))
                self.leg_note[leg] = why if clipped else None
                self._set_destination_locked(leg, t, k)
                if clipped:
                    notes.append("%s: %s" % (leg, why))
            self.action_note = ("the last known position is not fully reachable — %s"
                                % "; ".join(notes)) if notes else None
            self._state_dirty = True
        self.log.cmd("return_to_last", pose={str(k): v for k, v in pose.items()},
                     clipped=notes or None)
        return True

    def action_record(self, name=None):
        with self._lock:
            pos = {ch: int(self.current_us[ch]) for ch in self._action_channels()}
        a = self.actions.add(name, pos)
        self.log.cmd("action_record", id=a["id"], name=a["name"], pos=a["pos"])
        return a

    def action_run(self, aid):
        a = self.actions.get(aid)
        if a is None:
            return False
        notes = []
        with self._lock:
            if self.estopped:
                return False
            for leg in LEGS:
                dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
                c = self.corridors.get(leg)
                if dch is None or pch is None or c is None or not c.ok:
                    continue
                t_want, k_want = a["pos"].get(dch), a["pos"].get(pch)
                if t_want is None and k_want is None:
                    continue
                t0, k0 = self.current_us[dch], self.current_us[pch]
                t, k, clipped, why = corr_mod.reach(
                    c, t0, k0,
                    t0 if t_want is None else t_want,
                    k0 if k_want is None else k_want)
                self.leg_note[leg] = why if clipped else None
                self._set_destination_locked(leg, t, k)
                for ch in (dch, pch):
                    if self.enabled.get(ch):
                        self.driven[ch] = True
                if clipped:
                    notes.append("%s: %s" % (leg, why))
            self.action_note = ("“%s” could not be reached in full — %s"
                                % (a["name"], "; ".join(notes))) if notes else None
            self._state_dirty = True
        self.log.cmd("action_run", id=a["id"], name=a["name"], pos=a["pos"],
                     clipped=notes or None)
        return True

    def set_speed(self, us_per_s):
        with self._lock:
            self.speed_us_per_s = self._clamp_speed(us_per_s)
            self._save_servo_config()
        return self.speed_us_per_s

    def set_pulse(self, us=None, delay_ms=None):
        with self._lock:
            if us is not None:
                try:
                    self.pulse_us = max(0, min(PULSE_US_MAX, int(float(us))))
                except (TypeError, ValueError):
                    pass
                if self.pulse_us <= 0:
                    for leg in LEGS:
                        g = self.goal.get(leg)
                        if g:
                            self._aim(self._ch(leg, THIGH), g[0])
                            self._aim(self._ch(leg, KNEE), g[1])
                        self.goal[leg] = None
                    self._pulse_leg = None
                    self._pulse_done = None
            if delay_ms is not None:
                try:
                    self.pulse_delay_s = max(PULSE_DELAY_MIN_MS,
                                             min(PULSE_DELAY_MAX_MS,
                                                 int(float(delay_ms)))) / 1000.0
                except (TypeError, ValueError):
                    pass
            self._save_servo_config()
        self.log.cmd("pulse_set", us=self.pulse_us,
                     delay_ms=int(self.pulse_delay_s * 1000))
        return True

    def engage(self, leg=None):
        with self._lock:
            if self.estopped:
                return False
            n = 0
            for ch in CHANNELS:
                s = self._slot(ch)
                if leg is not None and not (s and s[0] == leg):
                    continue
                if not self.enabled.get(ch):
                    continue
                self.target_us[ch] = self.current_us[ch]
                self.driven[ch] = True
                n += 1
            self.test_note = None
            if leg is None:
                if not n:
                    self.action_note = ("nothing was engaged — every motor is switched "
                                        "off in the Hardware table")
                return n > 0
            pair = [c for c in (self._ch(leg, THIGH), self._ch(leg, KNEE))
                    if c is not None]
            off = [self.names[c] for c in pair if not self.enabled.get(c)]
            self.leg_note[leg] = (None if not off else
                "%s %s switched off, so Engage cannot hold this leg — tick “on” for "
                "%s in the Hardware table above."
                % (" and ".join(off), "is" if len(off) == 1 else "are",
                   "it" if len(off) == 1 else "them"))
        return not off

    def relax(self, leg=None):
        with self._lock:
            for ch in CHANNELS:
                s = self._slot(ch)
                if leg is not None and not (s and s[0] == leg):
                    continue
                self.driven[ch] = False
            self._drop_goals(leg)
        return True

    def _drop_goals(self, leg=None):
        for l in ([leg] if leg else LEGS):
            if l in self.goal:
                self.goal[l] = None
        if leg is None or self._pulse_leg == leg:
            self._pulse_leg = None
            self._pulse_done = None

    def estop(self):
        with self._lock:
            self.estopped = True
            self._drop_goals()
            for ch in CHANNELS:
                self.driven[ch] = False
            if self.test_mode:
                old = {ch: self._map_span(ch) for ch in CHANNELS}
                self.test_mode = False
                for ch in CHANNELS:
                    self._remap_locked(ch, old[ch], self._map_span(ch))
                self.test_note = "stopped by the E-STOP"
        print("[suki] E-STOP - every output held at zero")
        return True

    def clear_estop(self):
        with self._lock:
            self.estopped = False
            self._drop_goals()
            for ch in CHANNELS:
                self.driven[ch] = False
        return True

    def _servo_row(self, ch):
        leg, joint, label = self._slot(ch)
        lo, hi = self._drivable_bounds(ch)
        cur = int(self.current_us[ch])
        edge_now, edge_span = self._edge_report(ch)
        return {
            "ch": ch, "leg": leg, "joint": joint, "name": label,
            "us": cur, "target": int(self.target_us[ch]),
            "phys": int(self.physical_us(ch)),
            "edge": bool(edge_now), "edge_span": bool(edge_span),
            "lo": int(lo), "hi": int(hi),
            "min": int(self.min_us[ch]), "max": int(self.max_us[ch]),
            "invert": bool(self.invert[ch]), "enabled": bool(self.enabled[ch]),
            "driven": bool(self.driven[ch]), "energised": self._energised(ch),
            "outside": bool(cur < lo or cur > hi),
            "rejects": int(self.rejects.get(ch, 0)),
            "last_reject": self.last_reject.get(ch),
        }

    def _leg_report(self, leg):
        c = self.corridors.get(leg)
        dch, pch = self._ch(leg, THIGH), self._ch(leg, KNEE)
        if c is None or dch is None or pch is None:
            return None
        out = {"leg": leg, "ok": bool(c.ok), "note": self.leg_note.get(leg),
               "points": c.points(), "thigh_ch": dch, "knee_ch": pch,
               "thigh_span": None, "knee_span": None, "safe_band": [],
               "knee_window": None}
        if not c.ok:
            return out
        out["thigh_span"] = [int(round(v)) for v in c.thigh_span()]
        out["knee_span"] = [int(round(v)) for v in c.knee_span()]
        out["safe_band"] = corr_mod.safe_band(c)
        w = c.window(self.current_us[dch])
        out["knee_window"] = [int(round(w[0])), int(round(w[1]))] if w else None
        return out

    def get_state(self):
        with self._lock:
            return {
                "build": BUILD_TAG,
                "mode": self.pca.mode,
                "estop": bool(self.estopped),
                "test": bool(self.test_mode),
                "test_span": [SAFE_MIN_US, SAFE_MAX_US],
                "test_note": self.test_note,
                "speed": int(self.speed_us_per_s),
                "speed_range": [SPEED_MIN_US_PER_S, SPEED_MAX_US_PER_S],
                "pca": self.pca.status(),
                "servos": [self._servo_row(ch) for ch in self._joint_order()
                           if ch is not None],
                "channels": [{"ch": ch,
                              "name": self.slots[ch][2] if self.slots[ch] else None}
                             for ch in CHANNELS],
                "legs": {leg: self._leg_report(leg) for leg in LEGS},
                "action_channels": self._action_channels(),
                "actions": self.actions.public(),
                "action_note": self.action_note,
                "boot_pose": {str(ch): int(v) for ch, v in self.boot_pose.items()},
                "pulse": {
                    "us": int(self.pulse_us),
                    "us_max": PULSE_US_MAX,
                    "delay_ms": int(self.pulse_delay_s * 1000),
                    "delay_min_ms": PULSE_DELAY_MIN_MS,
                    "delay_max_ms": PULSE_DELAY_MAX_MS,
                    "active": self._pulse_leg,
                    "pending": [leg for leg in LEGS if self.goal.get(leg)],
                },
                "loop": {"hz": round(self.tick_hz, 1),
                         "late": int(self.ticks_late),
                         "rt": bool(self.rt)},
            }

    def shutdown(self):
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._saver.join(timeout=1.0)
        try:
            self._save_state()
            if self._corridor_dirty:
                self._save_corridor()
        except OSError:
            pass
        self.pca.shutdown()
        self.log.info("shutdown")
        self.log.flush()
