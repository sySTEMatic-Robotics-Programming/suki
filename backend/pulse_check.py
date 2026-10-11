import time

from config import CH, KNEE, THIGH
from controller import Controller


def travel_time(r, leg, frm, to, knee, limit=20.0):
    dch = r._ch(leg, THIGH)
    r.set_leg_pair(leg, thigh_us=frm, knee_us=knee)
    t0 = time.monotonic()
    while abs(r.current_us[dch] - frm) > 2 and time.monotonic() - t0 < limit:
        time.sleep(0.01)
    time.sleep(0.3)
    r.set_leg_pair(leg, thigh_us=to, knee_us=knee)
    t0 = time.monotonic()
    while abs(r.current_us[dch] - to) > 2 and time.monotonic() - t0 < limit:
        time.sleep(0.005)
    return time.monotonic() - t0


def pulse_events(r, since):
    return [e for e in r.log.tail(4000, "info")
            if e.get("k") == "pulse" and e.get("t", 0) >= since]


def check():
    r = Controller(force_sim=True)
    try:
        LEG, OTHER = "FR", "FL"
        for leg in (LEG, OTHER):
            for j in (THIGH, KNEE):
                r.set_servo_config(CH[(leg, j)], enabled=True)
        r.engage()
        time.sleep(0.3)

        span = r.corridors[LEG].thigh_span()
        lo, hi = int(span[0]) + 5, int(span[1]) - 5
        knee = int(sum(r.corridors[LEG].window(lo)) / 2)
        dist = hi - lo
        assert dist > 300, "need a real distance to time"

        r.set_pulse(us=0)
        cont = travel_time(r, LEG, lo, hi, knee)
        ideal = dist / float(r.speed_us_per_s)
        assert cont < ideal * 1.6, "even continuous motion is late: %.2fs vs %.2fs" % (
            cont, ideal)

        r.set_pulse(us=40, delay_ms=0)
        assert r.pulse_delay_s == 0.0, "delay 0 must be accepted"
        pulsed = travel_time(r, LEG, hi, lo, knee)
        assert pulsed <= cont * 1.25, (
            "pulsed motion is still stopping between pulses: %.2fs vs %.2fs continuous"
            % (pulsed, cont))

        evs = pulse_events(r, time.time() - pulsed - 1)
        assert len(evs) == 1, "one leg should be one continuous move, got %d" % len(evs)
        assert evs[0]["leg"] == LEG and evs[0]["step"] is None, evs[0]

        GAP_MS = 120
        r.set_pulse(us=40, delay_ms=GAP_MS)
        r.set_leg_pair(LEG, thigh_us=hi, knee_us=knee)
        r.set_leg_pair(OTHER, thigh_us=int(r.corridors[OTHER].thigh_span()[1]) - 5,
                       knee_us=int(sum(r.corridors[OTHER].window(
                           r.current_us[r._ch(OTHER, THIGH)])) / 2))
        mark = time.time()
        time.sleep(3.0)
        evs = pulse_events(r, mark)
        assert len({e["leg"] for e in evs}) == 2, "both legs should have had a turn"
        handovers = 0
        for a, b in zip(evs, evs[1:]):
            if a["leg"] != b["leg"]:
                handovers += 1
                gap = b["t"] - a["t"]
                assert gap >= GAP_MS / 1000.0 * 0.75, (
                    "%s -> %s only %.0f ms apart; the rail gets no rest"
                    % (a["leg"], b["leg"], gap * 1000))
        assert handovers >= 2, "expected the legs to alternate, saw %d" % handovers

        assert r._pulse_leg is None or isinstance(r._pulse_leg, str)
        moving = 0
        for _ in range(120):
            prev = {l: (r.current_us[r._ch(l, THIGH)], r.current_us[r._ch(l, KNEE)])
                    for l in (LEG, OTHER)}
            time.sleep(0.02)
            now = {l: (r.current_us[r._ch(l, THIGH)], r.current_us[r._ch(l, KNEE)])
                   for l in (LEG, OTHER)}
            n = sum(1 for l in (LEG, OTHER) if prev[l] != now[l])
            moving = max(moving, n)
        assert moving <= 1, "two legs moved in the same instant - the surge is back"

        print("pulse: one leg %.2fs pulsed vs %.2fs continuous (%.0f%%), "
              "handover gap held, one leg at a time — all checks passed"
              % (pulsed, cont, 100.0 * pulsed / cont))
    finally:
        r.set_pulse(us=0)
        r.shutdown()


if __name__ == "__main__":
    check()
