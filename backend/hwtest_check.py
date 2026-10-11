import os
import shutil
import time

from config import (ACTIONS_FILE, CH, CHANNELS, CORRIDOR_FILE, HIP, KNEE,
                    SAFE_MAX_US, SAFE_MIN_US, SERVO_CONFIG_FILE, STATE_FILE, THIGH)
from controller import Controller

_HERE = os.path.dirname(os.path.abspath(__file__))
_FILES = (SERVO_CONFIG_FILE, CORRIDOR_FILE, STATE_FILE, ACTIONS_FILE)


def settle(secs):
    time.sleep(secs)


def check():
    r = Controller(force_sim=True)
    try:
        FR_T, FR_K = CH[("FR", THIGH)], CH[("FR", KNEE)]
        assert r.invert[FR_T] and not r.invert[FR_K], "fixture assumes ch12 inverted"

        for c in (FR_T, FR_K, CH[("BL", KNEE)], CH[("FR", HIP)]):
            r.set_servo_config(c, enabled=True)

        before = {ch: r.physical_us(ch) for ch in r.min_us}
        assert r.set_test_mode(True)
        assert {ch: r.physical_us(ch) for ch in r.min_us} == before
        assert r.test_mode

        assert r._travel_bounds(FR_T) == (SAFE_MIN_US, SAFE_MAX_US)
        assert r._corridor_bounds(FR_T) is None

        assert r.set_test_us(FR_T, SAFE_MAX_US)
        settle(2.5)
        assert r.current_us[FR_T] == SAFE_MAX_US, r.current_us[FR_T]
        assert r.physical_us(FR_T) == SAFE_MIN_US, r.physical_us(FR_T)
        assert r.out_duty[FR_T] > 0

        assert r.set_test_us(FR_K, 2200)
        settle(2.0)
        assert r.current_us[FR_K] == 2200, r.current_us[FR_K]
        assert r.physical_us(FR_K) == 2200
        assert r.max_us[FR_K] < 2200, "2200 must be outside this knee's calibration"

        BL_K = CH[("BL", KNEE)]
        assert r.invert[BL_K] and r.max_us[BL_K] < 2000
        for want, wire in ((SAFE_MAX_US, SAFE_MIN_US), (SAFE_MIN_US, SAFE_MAX_US)):
            assert r.set_test_us(BL_K, want)
            settle(3.0)
            assert r.current_us[BL_K] == want, (want, r.current_us[BL_K])
            assert r.physical_us(BL_K) == wire, (want, r.physical_us(BL_K))
            assert r.rejects[BL_K] == 0, r.last_reject[BL_K]
            assert r.out_duty[BL_K] > 0

        k0 = r.current_us[BL_K]
        r.set_test_us(BL_K, SAFE_MAX_US)
        time.sleep(0.1)
        assert abs(r.current_us[BL_K] - k0) <= r.speed_us_per_s * 0.25
        settle(3.0)

        w = r.physical_us(FR_T)
        assert r.set_servo_config(FR_T, invert=False)
        assert r.physical_us(FR_T) == w, (r.physical_us(FR_T), w)
        assert r.set_servo_config(FR_T, invert=True)
        assert r.physical_us(FR_T) == w
        assert r.current_us[FR_T] == SAFE_MAX_US

        assert r.set_leg_pair("FR", thigh_us=2000, knee_us=1700) is False
        assert r.set_servo(FR_T, 2000) is False
        assert "hardware test" in (r.leg_note["FR"] or "")

        w_all = {ch: r.physical_us(ch) for ch in r.min_us}
        assert r.set_test_mode(False)
        assert not r.test_mode
        assert {ch: r.physical_us(ch) for ch in r.min_us} == w_all
        assert r._travel_bounds(FR_T) == r._static_bounds(FR_T)
        assert not r.driven[FR_T] and not r.driven[FR_K]
        assert "outside" in (r.test_note or ""), r.test_note
        assert r.set_test_us(FR_T, 600) is False

        assert r.set_test_mode(True)
        r.estop()
        assert not r.test_mode
        assert r.set_test_mode(True) is False
        r.clear_estop()

        r.engage("FR")
        settle(0.3)
        w = r.physical_us(FR_T)
        assert r.set_servo_config(FR_T, min_us=600)
        assert r.physical_us(FR_T) == w, (r.physical_us(FR_T), w)
        assert r.set_servo_config(FR_T, min_us=500)
        assert r.physical_us(FR_T) == w

        rows = r.corridors["FR"].points()
        assert r.set_servo_config(FR_T, invert=False)
        assert r.physical_us(FR_T) == w
        assert r.corridors["FR"].points() != rows
        assert r.set_servo_config(FR_T, invert=True)
        assert r.physical_us(FR_T) == w
        assert r.corridors["FR"].points() == rows

        span = r.corridors["FR"].thigh_span()
        assert r.set_leg_pair("FR", thigh_us=span[0], knee_us=1750)
        settle(3.0)
        assert r.corridors["FR"].contains(r.current_us[FR_T], r.current_us[FR_K])

        r.engage()
        settle(0.3)
        assert any(r._energised(c) for c in r.min_us)
        a, b = FR_T, CH[("BL", KNEE)]
        keep = {c: (r.min_us[c], r.max_us[c], r.invert[c], r.enabled[c],
                    r.current_us[c], r.names[c]) for c in (a, b)}
        pose = dict(r.action_record("wiring check")["pos"])

        assert r.set_channel_slot(a, "BL", KNEE)
        assert r._ch("BL", KNEE) == a and r._ch("FR", THIGH) == b
        assert not any(r._energised(c) for c in r.min_us), "a re-wire must cut torque"
        for src, dst in ((a, b), (b, a)):
            assert (r.min_us[dst], r.max_us[dst], r.invert[dst], r.enabled[dst],
                    r.current_us[dst], r.names[dst]) == keep[src], dst
        now = r.actions.get(r.actions.actions[-1]["id"])["pos"]
        assert now.get(a) == pose.get(b) and now.get(b) == pose.get(a), (pose, now)
        assert a in r._action_channels() and b in r._action_channels()

        assert r.set_channel_slot(a, "FR", THIGH)
        assert r._ch("FR", THIGH) == a and r._ch("BL", KNEE) == b
        for c in (a, b):
            assert (r.min_us[c], r.max_us[c], r.invert[c], r.enabled[c],
                    r.current_us[c], r.names[c]) == keep[c], c
        assert r.actions.get(r.actions.actions[-1]["id"])["pos"] == pose
        r.actions.delete(r.actions.actions[-1]["id"])

        assert r.set_channel_slot(a, "FR", THIGH) is True
        assert r.set_channel_slot(a, "FR", "elbow") is False
        assert r.set_channel_slot(99, "FR", KNEE) is False

        free = [c for c in CHANNELS if r._slot(c) is None]
        assert sorted(free) == [3, 7, 11, 15], free
        for c in free:
            assert not r.enabled[c], "an output with no joint on it must be off"
        keep_a = (r.min_us[a], r.max_us[a], r.invert[a], r.names[a], r.current_us[a])

        assert r.set_channel_slot(3, "FR", THIGH)
        assert r._ch("FR", THIGH) == 3 and r._slot(a) is None
        assert (r.min_us[3], r.max_us[3], r.invert[3], r.names[3],
                r.current_us[3]) == keep_a
        assert r.enabled[3] and not r.enabled[a]
        assert 3 in r._action_channels() and a not in r._action_channels()
        r.engage("FR")
        settle(0.3)
        assert r.set_leg_pair("FR", thigh_us=span[0], knee_us=1750)
        settle(3.0)
        assert r.corridors["FR"].contains(r.current_us[3], r.current_us[FR_K])
        assert r.get_state()["servos"][0]["ch"] is not None
        assert len(r.get_state()["servos"]) == 12
        assert len(r.get_state()["channels"]) == 16

        assert r.set_channel_slot(a, "FR", THIGH)
        assert r._ch("FR", THIGH) == a and r._slot(3) is None
        assert not r.enabled[3]

        r.relax()
        hip = CH[("FR", HIP)]
        assert r.set_servo_config(hip, enabled=False)
        assert r.set_test_mode(True)
        assert not r.enabled[hip] and not r._energised(hip)
        assert r.set_test_us(hip, 1600) is False
        assert "switched off" in (r.test_note or ""), r.test_note
        assert r.set_servo_config(hip, enabled=True)
        assert r._energised(hip), "switching a channel on mid-test must drive it"
        before = r.current_us[hip]
        assert r.set_test_us(hip, 2400)
        settle(2.0)
        assert r.current_us[hip] != before and r.out_duty[hip] > 0
        assert r.set_test_mode(False)

        for c in (FR_T, FR_K):
            assert r.set_servo_config(c, enabled=False)
        assert r.set_servo_config(hip, enabled=True)
        assert r.engage("FR") is False, "a leg whose pair is off is not engaged"
        assert "switched off" in (r.leg_note["FR"] or ""), r.leg_note["FR"]
        assert r._energised(hip), "the hip is enabled, so it still engages"
        assert r.set_servo_config(FR_T, enabled=True)
        assert r.engage("FR") is False, "one of the pair is still off"
        assert "Front-Right knee" in (r.leg_note["FR"] or ""), r.leg_note["FR"]
        assert r.set_servo_config(FR_K, enabled=True)
        assert r.engage("FR") is True
        assert r.leg_note["FR"] is None
        assert r._energised(FR_T) and r._energised(FR_K)
        assert r.set_servo_config(hip, enabled=True)

        print("hardware test mode + channel map + silent-refusal: all checks passed")
    finally:
        r.shutdown()


def main():
    saved = {}
    for name in _FILES:
        p = os.path.join(_HERE, name)
        if os.path.exists(p):
            saved[p] = p + ".hwcheck.bak"
            shutil.copy2(p, saved[p])
    try:
        check()
    finally:
        for p, bak in saved.items():
            os.replace(bak, p)


if __name__ == "__main__":
    main()
