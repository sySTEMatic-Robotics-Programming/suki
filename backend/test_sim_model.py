import json
import math
import os
import sys

import config

FAILS = []
HERE = os.path.dirname(os.path.abspath(__file__))
LEGS = ("FR", "FL", "BR", "BL")
L1 = config.LEG_GEOMETRY["l_upper"]
L2 = config.LEG_GEOMETRY["l_lower"]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  FAIL  %s" % msg)


def interp(x, pts, xi=0, yi=1):
    p = sorted(pts, key=lambda q: q[xi])
    a, b = (p[0], p[1]) if x <= p[0][xi] else (p[-2], p[-1])
    if p[0][xi] < x < p[-1][xi]:
        for i in range(1, len(p)):
            if x <= p[i][xi]:
                a, b = p[i - 1], p[i]
                break
    return a[yi] + (x - a[xi]) / (b[xi] - a[xi]) * (b[yi] - a[yi])


def forward(thigh_deg, knee_deg):
    t = math.radians(thigh_deg)
    kx, ky = L1 * math.sin(t), L1 * math.cos(t)
    r = math.radians(knee_deg)
    bx, by = -math.sin(t), -math.cos(t)
    return (kx + L2 * (bx * math.cos(r) - by * math.sin(r)),
            ky + L2 * (bx * math.sin(r) + by * math.cos(r)))


def foot_of(leg, thigh_us, knee_us):
    tc, kc = config.CH[(leg, "thigh")], config.CH[(leg, "knee")]
    return forward(interp(thigh_us, config.JOINT_ANGLE_POINTS[tc]),
                   interp(knee_us, config.JOINT_ANGLE_POINTS[kc]))


def test_poses_stand_square():
    print("five verified poses, all four feet:")
    for p in config.VERIFIED_POSES:
        feet = [foot_of(leg, p["pos"][config.CH[(leg, "thigh")]],
                        p["pos"][config.CH[(leg, "knee")]]) for leg in LEGS]
        dx = max(f[0] for f in feet) - min(f[0] for f in feet)
        dy = max(f[1] for f in feet) - min(f[1] for f in feet)
        print("  %-11s x %7.1f  y %7.1f   spread %.2f / %.2f mm"
              % (p["name"], feet[0][0], feet[0][1], dx, dy))
        check(dx < 0.5 and dy < 0.5,
              "%s: the four legs disagree by %.2f/%.2f mm - a JOINT_ANGLE_POINTS row is "
              "wrong, or that pose was never actually square" % (p["name"], dx, dy))
        check(feet[0][0] < 0,
              "%s puts the foot %+.1f mm, in FRONT of the hip - the Simulator's stance "
              "centre assumes every pose is behind it" % (p["name"], feet[0][0]))


def test_stand_band():
    ys = [foot_of(leg, p["pos"][config.CH[(leg, "thigh")]],
                  p["pos"][config.CH[(leg, "knee")]])[1]
          for p in config.VERIFIED_POSES for leg in LEGS]
    lo, hi = min(ys), max(ys)
    print("stand band from the poses: %.1f .. %.1f mm" % (lo, hi))
    check(hi - lo > 10, "the ladder spans only %.1f mm - too little to call a band"
          % (hi - lo))
    check(lo > 160, "lowest pose is %.1f mm; the old 150 mm default would be inside the "
                    "band, so the re-range buys nothing" % lo)
    check(hi < L1 + L2, "highest pose is %.1f mm, past the %.0f mm the linkage has"
          % (hi, L1 + L2))


def test_step_set_is_legal():
    cor = json.load(open(os.path.join(HERE, "corridor.json")))
    worst = 0.0
    for leg in LEGS:
        pts = config._WALK_STEP[leg]
        nodes = cor[leg]["points"]
        for i, p in enumerate(pts):
            check(config.SAFE_MIN_US <= p["thigh"] <= config.SAFE_MAX_US,
                  "%s point %d thigh %d us is outside the servo-safe window"
                  % (leg, i, p["thigh"]))
            check(0.0 <= p["k"] <= 1.0,
                  "%s point %d has k=%.3f, which is not a fraction" % (leg, i, p["k"]))
            d = p["thigh"]
            inside = nodes[0]["drive"] - 1 <= d <= nodes[-1]["drive"] + 1
            check(inside, "%s point %d thigh %d us is outside the measured corridor "
                          "(%d..%d) - it has no knee band to be a fraction of"
                          % (leg, i, d, nodes[0]["drive"], nodes[-1]["drive"]))
            worst = max(worst, p["k"])
    print("step set: %d points x 4 legs, all inside their corridors (deepest fold "
          "k=%.3f)" % (len(config._WALK_STEP["FR"]), worst))
    check(worst < 0.999, "a point sits at k=%.4f, hard against the top of the band - "
                         "the shape was clamped, not fitted" % worst)


def test_step_back_is_the_same_loop():
    fwd = [s for s in config.WALK_SEED if s["name"] == "step"]
    bak = [s for s in config.WALK_SEED if s["name"] == "step back"]
    check(fwd and bak, "the step / step back pair is not in WALK_SEED")
    if not (fwd and bak):
        return
    for leg in LEGS:
        a = [(p["thigh"], p["k"]) for p in fwd[0]["legs"][leg]]
        b = [(p["thigh"], p["k"]) for p in bak[0]["legs"][leg]]
        check(a == list(reversed(b)),
              "%s: 'step back' is not 'step' reversed" % leg)
    print("'step back' is 'step' traversed the other way, on all four legs")


def test_step_set_matches_the_file():
    path = os.path.join(HERE, config.WALK_FILE)
    if not os.path.exists(path):
        print("no walk_points.json yet - the seed is all there is, nothing to compare")
        return
    stored = json.load(open(path))
    for seed in config.WALK_SEED:
        if seed["name"] not in ("step", "step back"):
            continue
        got = [s for s in stored.get("sets", []) if s.get("name") == seed["name"]]
        if not got:
            print("walk_points.json has no %r set - it predates this design"
                  % seed["name"])
            continue
        for leg in LEGS:
            a = [(p["thigh"], round(p["k"], 4)) for p in seed["legs"][leg]]
            b = [(p["thigh"], round(p["k"], 4)) for p in got[0]["legs"][leg]]
            check(a == b, "%s: the stored %r set and the seed in config.py have drifted "
                          "apart" % (leg, seed["name"]))
        print("stored %r set matches the seed in config.py" % seed["name"])


def test_reach_is_what_limits_the_step():
    cor = json.load(open(os.path.join(HERE, "corridor.json")))
    print("shortest each leg can make itself:")
    dmin = {}
    for leg in LEGS:
        kc = config.CH[(leg, "knee")]
        us = [n[k] for n in cor[leg]["points"] for k in ("min", "max")]
        angles = [interp(u, config.JOINT_ANGLE_POINTS[kc]) for u in us]
        k = min(angles)
        dmin[leg] = math.sqrt(L1 * L1 + L2 * L2 - 2 * L1 * L2 * math.cos(math.radians(k)))
        print("  %s  knee folds to %5.1f deg  ->  leg as short as %.1f mm"
              % (leg, k, dmin[leg]))
    tight = max(dmin, key=dmin.get)
    check(dmin[tight] < L1 + L2, "%s cannot fold at all" % tight)
    stand, centre = 180.0, -32.0
    lift = stand - math.sqrt(max(0.0, dmin[tight] ** 2 - centre ** 2))
    print("  at 180 mm stand, x %+d mm: %s gives %.1f mm of clearance"
          % (centre, tight, lift))
    check(lift > 0, "no leg leaves the floor at the default stance - the default step "
                    "height is a fiction")
    check(lift < 30, "clearance is %.1f mm, so the old 30 mm default was reachable "
                     "after all and this whole design is built on a wrong number" % lift)


if __name__ == "__main__":
    for fn in (test_poses_stand_square, test_stand_band, test_step_set_is_legal,
               test_step_back_is_the_same_loop, test_step_set_matches_the_file,
               test_reach_is_what_limits_the_step):
        print("\n== %s" % fn.__name__)
        fn()
    print("\n%s" % ("FAILED: %d" % len(FAILS) if FAILS else
                    "all simulator-model checks passed"))
    sys.exit(1 if FAILS else 0)
