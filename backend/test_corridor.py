import math
import sys

import corridor as C
from config import CORRIDOR_SEED

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  FAIL  %s" % msg)


def legs():
    return {leg: C.Corridor(pts) for leg, pts in CORRIDOR_SEED.items()}


def test_windows():
    print("windows interpolate through the measured rows")
    for leg, c in legs().items():
        check(c.ok, "%s should have a usable corridor" % leg)
        for d, lo, hi in c.rows:
            w = c.window(d)
            check(abs(w[0] - lo) < 1e-6 and abs(w[1] - hi) < 1e-6,
                  "%s: window at a captured row must BE that row (%s vs %s)"
                  % (leg, w, (lo, hi)))
        a, b = c.rows[0], c.rows[1]
        mid = (a[0] + b[0]) / 2.0
        w = c.window(mid)
        check(abs(w[0] - (a[1] + b[1]) / 2.0) < 1e-6,
              "%s: midpoint of two rows must be the midpoint of their bounds" % leg)
        lo_t, hi_t = c.thigh_span()
        check(c.window(lo_t - 500) == (c.rows[0][1], c.rows[0][2]),
              "%s: below the span the window must clamp, never extrapolate" % leg)
        check(c.window(hi_t + 500) == (c.rows[-1][1], c.rows[-1][2]),
              "%s: above the span the window must clamp, never extrapolate" % leg)


def test_contains():
    print("containment refuses anything off the chart")
    c = legs()["FR"]
    lo_t, hi_t = c.thigh_span()
    w = c.window(lo_t)
    check(c.contains(lo_t, w[0]) and c.contains(lo_t, w[1]),
          "the window edges must count as inside")
    check(not c.contains(lo_t, w[0] - 1), "one us below the window is outside")
    check(not c.contains(lo_t, w[1] + 1), "one us above the window is outside")
    check(not c.contains(lo_t - 1, w[0]), "one us before the span is outside")
    check(not c.contains(hi_t + 1, w[0]), "one us past the span is outside")


def test_reach_accepts_legal():
    print("reach passes a legal move through untouched")
    for leg, c in legs().items():
        lo_t, hi_t = c.thigh_span()
        t0 = int(lo_t) + 20
        k0 = int(round(sum(c.window(t0)) / 2))
        t1 = int(hi_t) - 20
        k1 = int(round(sum(c.window(t1)) / 2))
        t, k, clipped, _why = C.reach(c, t0, k0, t1, k1)
        check(not clipped, "%s: a legal mid-corridor move must not be clipped" % leg)
        check(t == t1 and abs(k - k1) <= 1,
              "%s: reach must land on the requested pair (got %s,%s want %s,%s)"
              % (leg, t, k, t1, k1))
        check(C.path_clear(c, t0, k0, t, k),
              "%s: the whole path must be inside the corridor" % leg)


def test_reach_clips_outside():
    print("reach clips a target off the end of the chart")
    c = legs()["FR"]
    lo_t, hi_t = c.thigh_span()
    t0 = int(lo_t) + 50
    k0 = int(round(sum(c.window(t0)) / 2))
    t, _k, clipped, why = C.reach(c, t0, k0, hi_t + 400, 1500)
    check(clipped and why, "asking past the captured extent must be clipped and said")
    check(t <= hi_t, "the thigh must not be allowed past the captured extent")
    t, k, clipped, _why = C.reach(c, t0, k0, t0, 900)
    check(clipped, "a knee below its window must be clipped")
    check(c.contains(t, k), "...and the result must still be inside the corridor")


def test_reach_stops_at_a_pinch():
    print("reach stops before a pinch instead of driving through it")
    c = C.Corridor([{"drive": 1500, "min": 1200, "max": 1400},
                    {"drive": 2000, "min": 1300, "max": 1300},
                    {"drive": 2500, "min": 1200, "max": 1400}])
    t, k, clipped, why = C.reach(c, 1500, 1300, 2500, 1300)
    check(clipped and why, "a move across a pinch must be clipped and explained")
    check(t < 2000, "must stop on the near side of the closure (stopped at %s)" % t)
    check(C.path_clear(c, 1500, 1300, t, k),
          "the clipped path must be clear end to end")
    t, k, clipped, _why = C.reach(c, 2500, 1300, 1500, 1300)
    check(clipped and t > 2000, "the pinch must block travel in both directions")
    check(C.path_clear(c, 2500, 1300, t, k), "the reverse clipped path must be clear")


def test_curved_band_needs_the_clamped_path():
    print("a curved band that a straight line would cut across")
    c = C.Corridor([{"drive": 1000, "min": 1000, "max": 1100},
                    {"drive": 1500, "min": 1400, "max": 1500},
                    {"drive": 2000, "min": 1000, "max": 1100}])
    check(not c.contains(1500, 1050), "the test corridor must actually bulge")
    t, k, clipped, _why = C.reach(c, 1000, 1050, 2000, 1050)
    check(not clipped, "the move IS reachable - the band never closes")
    check((t, k) == (2000, 1050), "and it must land exactly where it was asked")
    check(C.path_clear(c, 1000, 1050, 2000, 1050),
          "the clamped path must ride the bulge instead of cutting across it")


def drive(c, t0, k0, t1, k1, s, ticks=4000):
    t, k = t0, k0
    trail = [(t, k)]
    for _ in range(ticks):
        nt, nk = C.step(c, t, k, t1, k1, s)
        trail.append((nt, nk))
        if (nt, nk) == (t, k):
            break
        t, k = nt, nk
    return t, k, trail


def test_step_respects_the_speed_limit():
    print("no tick moves a joint further than the speed limit allows")
    for leg, c in legs().items():
        lo_t, hi_t = c.thigh_span()
        t0 = int(lo_t)
        k0 = int(round(sum(c.window(t0)) / 2))
        for s in (1.2, 6.0, 18.0, 48.0):
            t, k, trail = drive(c, t0, k0, int(hi_t), 1800, s)
            for (a, b), (x, y) in zip(trail, trail[1:]):
                check(abs(x - a) <= s + 1,
                      "%s: thigh moved %.1fus in one tick at limit %.1f"
                      % (leg, abs(x - a), s))
                check(abs(y - b) <= s + 1,
                      "%s: knee moved %.1fus in one tick at limit %.1f"
                      % (leg, abs(y - b), s))


def test_every_tick_stays_inside():
    print("EVERY intermediate position of a full sweep is inside the corridor")
    for leg, c in legs().items():
        lo_t, hi_t = c.thigh_span()
        klo, khi = c.knee_span()
        starts = [(int(lo_t), None), (int(hi_t), None),
                  (int((lo_t + hi_t) / 2), None)]
        goals = [(int(lo_t), klo), (int(hi_t), klo), (int(hi_t), khi),
                 (int(lo_t), khi), (int((lo_t + hi_t) / 2), (klo + khi) // 2)]
        for t0, _ in starts:
            k0 = int(round(sum(c.window(t0)) / 2))
            for gt, gk in goals:
                t, k, trail = drive(c, t0, k0, gt, gk, 18.0)
                for i, (a, b) in enumerate(trail):
                    check(c.contains(a, b),
                          "%s: tick %d of %s->%s left the corridor at (%s, %s)"
                          % (leg, i, (t0, k0), (gt, gk), a, b))
                check(C.path_clear(c, t0, k0, t, k),
                      "%s: the executed path %s->%s must be clear"
                      % (leg, (t0, k0), (t, k)))


def test_step_converges():
    print("a commanded move actually arrives")
    for leg, c in legs().items():
        lo_t, hi_t = c.thigh_span()
        t0 = int(lo_t)
        k0 = int(round(sum(c.window(t0)) / 2))
        want_t = int(hi_t)
        want_k = int(round(sum(c.window(want_t)) / 2))
        t, k, trail = drive(c, t0, k0, want_t, want_k, 18.0)
        check(t == want_t, "%s: thigh should arrive at %d, stopped at %d"
              % (leg, want_t, t))
        check(abs(k - want_k) <= 1, "%s: knee should arrive at %d, stopped at %d"
              % (leg, want_k, k))
        check(len(trail) < 4000, "%s: the move should finish, not spin" % leg)


def test_thigh_waits_for_the_knee():
    print("a fast thigh waits for a slow knee instead of outrunning it")
    c = C.Corridor([{"drive": 1000, "min": 1000, "max": 1010},
                    {"drive": 1500, "min": 3000, "max": 3010}])
    t, k = 1000, 1005
    nt, nk = C.step(c, t, k, 1500, 3005, 10.0)
    check(nt - t <= 4, "the thigh advanced %dus while the knee could only do 10"
          % (nt - t))
    check(c.contains(nt, nk), "the gated pair must still be inside the corridor")


def test_out_of_window_knee_walks_back():
    print("a joint parked outside its window walks back, it does not teleport")
    c = legs()["FR"]
    lo_t, _hi_t = c.thigh_span()
    t0 = int(lo_t) + 200
    w = c.window(t0)
    k0 = int(w[0]) - 300
    s = 18.0
    t, k = t0, k0
    steps = 0
    while steps < 200:
        nt, nk = C.step(c, t, k, t0, int(round(sum(w) / 2)), s)
        check(abs(nk - k) <= s + 1,
              "the knee jumped %.0fus in one tick (limit %.0f)" % (abs(nk - k), s))
        if (nt, nk) == (t, k):
            break
        t, k = nt, nk
        steps += 1
    check(c.contains(t, k), "the pair must end up inside the corridor (got %s, %s)"
          % (t, k))
    check(steps >= 300 / s - 1, "it must take real time to come back, not one tick")


def test_locked_knee_pens_the_thigh():
    print("a limp knee pens its thigh in where the window still contains it")
    c = legs()["FR"]
    lo_t, hi_t = c.thigh_span()
    t0 = int(hi_t) - 100
    k0 = int(c.window(t0)[0]) + 5
    t, k = t0, k0
    for _ in range(500):
        nt, nk = C.step(c, t, k, int(lo_t), k0, 18.0, knee_follows=False)
        check(nk == k, "a knee that cannot follow must not be moved")
        if nt == t:
            break
        t = nt
    check(c.contains(t, k),
          "the thigh must stop while the fixed knee is still legal (got %s, %s)"
          % (t, k))


def test_safe_band_is_inside():
    print("the drawn safe area is inside the real corridor")
    for leg, c in legs().items():
        band = C.safe_band(c)
        check(band, "%s must produce a drawable band" % leg)
        for run in band:
            for x, lo, hi in run:
                check(lo <= hi, "%s: a band node must not be inverted" % leg)
                check(c.contains(x, lo) and c.contains(x, hi),
                      "%s: band node (%s, %s..%s) is outside the corridor"
                      % (leg, x, lo, hi))
    c = C.Corridor([{"drive": 1500, "min": 1200, "max": 1400},
                    {"drive": 2000, "min": 1300, "max": 1300},
                    {"drive": 2500, "min": 1200, "max": 1400}])
    check(len(C.safe_band(c)) == 2,
          "a corridor that closes in the middle must draw as two separate lobes")


def test_degenerate_corridors_refuse():
    print("an unusable corridor refuses to drive rather than falling back wide")
    for rows in ([], [{"drive": 2000, "min": 1200, "max": 1400}],
                 [{"drive": 2000, "min": 1200, "max": 1400},
                  {"drive": 2000, "min": 1000, "max": 1800}]):
        c = C.Corridor(rows)
        check(not c.ok, "%d row(s) at %d distinct positions is not a corridor"
              % (len(rows), len(c.rows)))
        t, k, clipped, why = C.reach(c, 2000, 1300, 2400, 1300)
        check(clipped and why, "...and reach must refuse it")
        check((t, k) == (2000, 1300), "...leaving the joint exactly where it was")
        check(C.step(c, 2000, 1300, 2400, 1300, 18.0) == (2000, 1300),
              "...and step must not move it either")


def main():
    for fn in (test_windows, test_contains, test_reach_accepts_legal,
               test_reach_clips_outside, test_reach_stops_at_a_pinch,
               test_curved_band_needs_the_clamped_path,
               test_step_respects_the_speed_limit, test_every_tick_stays_inside,
               test_step_converges, test_thigh_waits_for_the_knee,
               test_out_of_window_knee_walks_back, test_locked_knee_pens_the_thigh,
               test_safe_band_is_inside, test_degenerate_corridors_refuse):
        fn()
    print()
    if FAILS:
        print("%d FAILURE(S)" % len(FAILS))
        return 1
    print("all corridor checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
