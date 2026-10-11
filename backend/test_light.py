import sys

import cv2
import numpy as np

from vision import _classify_light, _light_counts, classify_light_full

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  FAIL  %s" % msg)


def lamp(bgr, frac=0.25, size=60, housing=(20, 20, 20)):
    img = np.full((size, size, 3), housing, np.uint8)
    r = int((frac * size * size / 3.14159) ** 0.5)
    cv2.circle(img, (size // 2, size // 2), r, bgr, -1)
    return img


RED = (30, 30, 235)
AMBER = (20, 170, 245)
GREEN = (60, 220, 60)
OFF = (30, 30, 34)


def test_three_colours_separate():
    print("%-14s%-8s%6s%8s   counts" % ("case", "colour", "frac", "margin"))
    for name, bgr, want in (("red", RED, "red"), ("amber", AMBER, "amber"),
                            ("green", GREEN, "green"), ("off", OFF, "none")):
        r = classify_light_full(lamp(bgr))
        print("%-14s%-8s%6.2f%8.2f   %s"
              % (name, r["colour"], r["frac"], r["margin"], r["counts"]))
        check(r["colour"] == want,
              "a %s lamp read as %r" % (name, r["colour"]))
        if want != "none":
            check(r["margin"] > 0.8,
                  "a plain %s lamp only beat its runner-up by %.0f%%"
                  % (name, r["margin"] * 100))


def test_a_dim_lamp_is_refused():
    r = classify_light_full(lamp(RED, frac=0.005))
    print("a lamp filling 0.5%% of the box reads: %r" % r["colour"])
    check(r["colour"] == "none", "a 0.5%% lamp still produced %r" % r["colour"])


def test_a_distant_washed_out_lamp_is_still_read():
    def washed(lit, w=15, h=39, sat=0.45, haze=70, jpeg=40):
        big = np.full((h * 8, w * 8, 3), 95, np.uint8)
        lamps = [(40, 40, 235), (25, 175, 245), (70, 215, 70)]
        for i, c in enumerate(lamps):
            col = (tuple(int(v * sat + 255 * (1 - sat) * 0.72) for v in c) if i == lit
                   else tuple(int(v * 0.35 + 60) for v in c))
            cv2.circle(big, (w * 4, int(h * 8 * (0.22 + 0.28 * i))), int(w * 2.1),
                       col, -1)
        big = cv2.add(big, np.full_like(big, haze // 3))
        small = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
        return cv2.imdecode(cv2.imencode(".jpg", small,
                                         [cv2.IMWRITE_JPEG_QUALITY, jpeg])[1],
                            cv2.IMREAD_COLOR)

    for name, lit in (("red", 0), ("amber", 1), ("green", 2)):
        roi = washed(lit)
        strict, _ = _light_counts(roi)
        r = classify_light_full(roi)
        print("  15x39 washed-out %-6s -> %-6s via %-7s (strict counts %s)"
              % (name, r["colour"], r.get("method"), strict))
        check(r["colour"] == name,
              "a distant washed-out %s lamp read as %r" % (name, r["colour"]))
        check(r.get("method") == "bright",
              "%s was expected to need the relative test; it used %r - the synthetic "
              "case is too clean to be testing what it claims to"
              % (name, r.get("method")))
        check(r["margin"] < 0.9,
              "the relative reading claims %s confidence" % r["margin"])


def test_nothing_is_invented_on_a_non_light():
    cases = {
        "unlit dark housing": np.full((39, 15, 3), 26, np.uint8),
        "flat grey box": np.full((39, 15, 3), 120, np.uint8),
        "flat white box": np.full((39, 15, 3), 245, np.uint8),
        "blue sky": np.dstack([np.full((39, 15), 200, np.uint8),
                               np.full((39, 15), 140, np.uint8),
                               np.full((39, 15), 90, np.uint8)]),
    }
    for name, img in cases.items():
        r = classify_light_full(img)
        print("  %-20s -> %s" % (name, r["colour"]))
        check(r["colour"] == "none", "%s produced %r" % (name, r["colour"]))


def test_live_is_still_two_way():
    for name, bgr in (("red", RED), ("amber", AMBER), ("green", GREEN), ("off", OFF)):
        got = _classify_light(lamp(bgr))
        print("  live %-6s -> %s" % (name, got))
        check(got in ("red", "green", "none"),
              "the live classifier returned %r - it has gained a third answer" % got)
    check(_classify_light(lamp(AMBER)) == "none",
          "amber now reads as something on the LIVE path; it has always been `none` "
          "there and nothing in this program knows what a robot does about amber")


def test_degenerate_crops():
    for bad in (None, np.zeros((0, 0, 3), np.uint8)):
        check(classify_light_full(bad)["colour"] == "none", "an empty crop was read")
        check(_classify_light(bad) == "none", "an empty crop was read on the live path")
    print("empty crops refused rather than throwing")


def test_label_matching():
    from lab import _is_light
    for good in ("traffic light", "Traffic_Light", "trafficlight", "TRAFFIC LIGHT"):
        check(_is_light(good), "%r was not recognised as a traffic light" % good)
    for bad in ("person", "stop sign", "lighthouse", "traffic cone", ""):
        check(not _is_light(bad), "%r was treated as a traffic light" % bad)
    print("light labels matched across vocabularies; 'lighthouse' and 'stop sign' not")


if __name__ == "__main__":
    for fn in (test_three_colours_separate, test_a_dim_lamp_is_refused,
               test_a_distant_washed_out_lamp_is_still_read,
               test_nothing_is_invented_on_a_non_light,
               test_live_is_still_two_way, test_degenerate_crops, test_label_matching):
        print("\n== %s" % fn.__name__)
        fn()
    print("\n%s" % ("FAILED: %d" % len(FAILS) if FAILS
                    else "all traffic-light checks passed"))
    sys.exit(1 if FAILS else 0)
