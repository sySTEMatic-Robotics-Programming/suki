BUILD_TAG = "2026-08-02-voice-1"

I2C_ADDRESS = 0x40
I2C_BUS = 1
PWM_FREQ_HZ = 50

SAFE_MIN_US = 500
SAFE_MAX_US = 2500
NEUTRAL_US = 1500

EDGE_WARN_US = 25

LEGS = ["FR", "FL", "BR", "BL"]

THIGH = "thigh"
KNEE = "knee"
HIP = "hip"

SERVOS = {
    0:  ("BL", THIGH, "Back-Left thigh"),
    1:  ("BL", KNEE,  "Back-Left knee"),
    2:  ("BL", HIP,   "Back-Left hip"),
    4:  ("BR", THIGH, "Back-Right thigh"),
    5:  ("BR", KNEE,  "Back-Right knee"),
    6:  ("BR", HIP,   "Back-Right hip"),
    8:  ("FL", THIGH, "Front-Left thigh"),
    9:  ("FL", KNEE,  "Front-Left knee"),
    10: ("FL", HIP,   "Front-Left hip"),
    12: ("FR", THIGH, "Front-Right thigh"),
    13: ("FR", KNEE,  "Front-Right knee"),
    14: ("FR", HIP,   "Front-Right hip"),
}
CHANNELS = list(range(16))

CH = {(leg, joint): ch for ch, (leg, joint, _lbl) in SERVOS.items()}

LEG_NAMES = {"FR": "Front-Right", "FL": "Front-Left",
             "BR": "Back-Right", "BL": "Back-Left"}

LEG_GEOMETRY = {
    "l_upper":     107.0,
    "l_lower":     138.0,
    "body_length": 230.0,
    "body_width":   78.0,
    "base_height": 150.0,
}

JOINT_ANGLE_POINTS = {
    12: [(2307.0, -52.0), (2500.0, -77.03)],
    13: [(1380.0, 96.99), (1589.0, 90.0)],
    4:  [(2137.0, -52.0), (2300.0, -77.03)],
    5:  [(1591.0, 96.99), (1800.0, 90.0)],
    8:  [(2304.0, -52.0), (2497.0, -77.03)],
    9:  [(1491.0, 96.99), (1800.0, 90.0)],
    0:  [(2240.0, -52.0), (2497.0, -77.03)],
    1:  [(1570.0, 96.99), (1800.0, 90.0)],
}
ANGLE_PROVISIONAL = set()

VERIFIED_POSES = [
    {"name": "SIT DOWN",
     "pos": {12: 2440, 13: 1529, 4: 2249, 5: 1740, 8: 2437, 9: 1712, 0: 2417, 1: 1734}},
    {"name": "P1",
     "pos": {12: 2406, 13: 1492, 4: 2221, 5: 1703, 8: 2403, 9: 1656, 0: 2372, 1: 1693}},
    {"name": "P2",
     "pos": {12: 2373, 13: 1455, 4: 2193, 5: 1666, 8: 2370, 9: 1601, 0: 2328, 1: 1652}},
    {"name": "P3",
     "pos": {12: 2340, 13: 1417, 4: 2165, 5: 1628, 8: 2337, 9: 1546, 0: 2284, 1: 1611}},
    {"name": "STAND TALL",
     "pos": {12: 2307, 13: 1380, 4: 2137, 5: 1591, 8: 2304, 9: 1491, 0: 2240, 1: 1570}},
]

SERVO_DEFAULTS = {
    0:  {"min": 500, "max": 2500, "invert": False, "enabled": True},
    1:  {"min": 500, "max": 1800, "invert": True,  "enabled": True},
    2:  {"min": 1000, "max": 1800, "invert": True, "enabled": False},
    4:  {"min": 500, "max": 2500, "invert": True,  "enabled": True},
    5:  {"min": 500, "max": 1800, "invert": False, "enabled": True},
    6:  {"min": 1050, "max": 1800, "invert": False, "enabled": False},
    8:  {"min": 500, "max": 2500, "invert": False, "enabled": True},
    9:  {"min": 500, "max": 1800, "invert": True,  "enabled": True},
    10: {"min": 700, "max": 1150, "invert": False, "enabled": False},
    12: {"min": 500, "max": 2500, "invert": True,  "enabled": True},
    13: {"min": 500, "max": 1800, "invert": False, "enabled": True},
    14: {"min": 1700, "max": 2050, "invert": False, "enabled": False},
}

CORRIDOR_SEED = {
    "FR": [
        {"drive": 1710, "min": 1694, "max": 1800},
        {"drive": 1892, "min": 1566, "max": 1800},
        {"drive": 2079, "min": 1377, "max": 1800},
        {"drive": 2320, "min": 1145, "max": 1800},
        {"drive": 2500, "min": 1275, "max": 1800},
    ],
    "FL": [
        {"drive": 1749, "min": 1663, "max": 1800},
        {"drive": 1870, "min": 1537, "max": 1800},
        {"drive": 2160, "min": 1272, "max": 1800},
        {"drive": 2358, "min": 1240, "max": 1800},
        {"drive": 2500, "min": 1246, "max": 1800},
    ],
    "BR": [
        {"drive": 1710, "min": 1694, "max": 1800},
        {"drive": 1892, "min": 1566, "max": 1800},
        {"drive": 2079, "min": 1377, "max": 1800},
        {"drive": 2304, "min": 1145, "max": 1800},
        {"drive": 2500, "min": 1275, "max": 1800},
    ],
    "BL": [
        {"drive": 1749, "min": 1710, "max": 1800},
        {"drive": 1870, "min": 1620, "max": 1800},
        {"drive": 2160, "min": 1320, "max": 1800},
        {"drive": 2358, "min": 1240, "max": 1800},
        {"drive": 2500, "min": 1244, "max": 1800},
    ],
}

MIN_CORRIDOR_POINTS = 2

TICK_HZ = 50
TELEMETRY_HZ = 10

DEFAULT_SPEED_US_PER_S = 900
SPEED_MIN_US_PER_S = 60
SPEED_MAX_US_PER_S = 2400

DEFAULT_PULSE_US = 0
PULSE_US_MAX = 400
DEFAULT_PULSE_DELAY_MS = 50
PULSE_DELAY_MIN_MS = 0
PULSE_DELAY_MAX_MS = 200

PULSE_ARRIVE_TIMEOUT_S = 3.0

PWM_REFRESH_S = 0.1

PCA_HEALTH_S = 0.2

PCA_FREQ_BAD_BEATS = 2

PCA_RESET_CONFIRM = 3
PCA_CONFIRM_GAP_S = 0.004

PCA_STORM_N = 1
PCA_STORM_WINDOW_S = 6.0

PCA_DUTY_TOLERANCE = 32

REJECT_LOG_S = 2.0

ACTION_CHANNELS = [ch for ch in sorted(SERVOS) if SERVOS[ch][1] != HIP]

ACTION_SEED = [
    {"name": "SIT DOWN", "pos": {0: 2500, 1: 1800, 4: 2500, 5: 1550,
                                 8: 2500, 9: 1750, 12: 2500, 13: 1600}},
    {"name": "P1", "pos": {0: 2350, 1: 1800, 4: 2350, 5: 1550,
                           8: 2350, 9: 1800, 12: 2350, 13: 1600}},
    {"name": "P2", "pos": {0: 2200, 1: 1800, 4: 2200, 5: 1600,
                           8: 2200, 9: 1800, 12: 2200, 13: 1680}},
    {"name": "P3", "pos": {0: 2200, 1: 1720, 4: 2200, 5: 1550,
                           8: 2240, 9: 1700, 12: 2250, 13: 1580}},
    {"name": "P4", "pos": {0: 2200, 1: 1580, 4: 2200, 5: 1480,
                           8: 2260, 9: 1600, 12: 2260, 13: 1530}},
    {"name": "P5", "pos": {0: 2200, 1: 1580, 4: 2200, 5: 1480,
                           8: 2260, 9: 1600, 12: 2260, 13: 1530}},
]

SERVO_CONFIG_FILE = "servo_config.json"
CORRIDOR_FILE = "corridor.json"
STATE_FILE = "state.json"
ACTIONS_FILE = "actions.json"

SEQ_FILE = "sequences.json"
SEQ_MAX = 12
SEQ_MAX_STEPS = 32
SEQ_HOLD_MAX = 10.0
SEQ_REPEAT_MAX = 50

SEQ_SETTLE_US = 2

SEQ_STEP_TIMEOUT_S = 15.0

SEQ_SEED = [
    {
        "name": "sit up",
        "reverse": False,
        "repeat": 1,
        "hold": 0.4,
        "steps": ["SIT DOWN", "P1", "P2", "P3", "P4"],
    },
    {
        "name": "sit down",
        "reverse": False,
        "repeat": 1,
        "hold": 0.4,
        "steps": ["P4", "P3", "P2", "P1", "SIT DOWN"],
    },
    {
        "name": "sit → P1-P4 → back",
        "reverse": True,
        "repeat": 1,
        "hold": 0.4,
        "steps": ["SIT DOWN", "P1", "P2", "P3", "P4"],
    },
]
WALK_FILE = "walk_points.json"

WALK_MAX_SETS = 12
WALK_MAX_POINTS = 64
WALK_DWELL_MAX = 10.0
WALK_COLOURS = ["#a855f7", "#22d3ee", "#fbbd23", "#36d399",
                "#fb7185", "#60a5fa", "#a3e635", "#fb923c"]

SKETCH_FILE = "sketch.json"
SKETCH_MAX_STROKES = 60
SKETCH_MAX_POINTS = 400
SKETCH_WIDTHS = [1.5, 3.0, 6.0]

SKETCH_COLOURS = [
    "#f87171", "#fb923c", "#fbbd23", "#a3e635",
    "#36d399", "#2dd4bf", "#22d3ee", "#60a5fa",
    "#818cf8", "#a855f7", "#e879f9", "#fb7185",
    "#e5e7eb", "#94a3b8",
]

LOG_FILE = "suki.log.jsonl"
LOG_MAX_BYTES = 4 * 1024 * 1024
LOG_PWM = True
LOG_FLUSH_S = 0.25

TICK_LATE_S = 0.010

MOTION_RT_PRIORITY = 10


MOVE_ON_START = False

CAMERA_INDEX = 0
CAMERA_SCAN_MAX = 6
CAMERA_MIN_WIDTH = 320
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 20

YOLO_MODEL = "yolo26n.pt"

LAB_DIR = "lab"
LAB_MAX_IMAGES = 60
LAB_MAX_UPLOAD_BYTES = 12 << 20
LAB_MAX_LONG_EDGE = 1280
LAB_THUMB_EDGE = 320
YOLO_CONF = 0.4
YOLO_IMGSZ = 256

import os

MIC_DEVICE = "plughw:CARD=Webcam,DEV=0"

MIC_RATE = 16000
MIC_CHUNK = 1024

MIC_CHANNELS = 2

MIC_DEVICE_MAX_LEN = 80

SILENCE_S = 0.7
MIN_UTTERANCE_S = 0.4
MAX_UTTERANCE_S = 8.0
PREROLL_CHUNKS = 5

WHISPER_BIN = os.environ.get(
    "WHISPER_BIN", os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli"))

WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL", os.path.expanduser("~/whisper.cpp/models/ggml-base-q5_1.bin"))
WHISPER_MODEL_DIR = os.path.dirname(WHISPER_MODEL)
WHISPER_MODEL_MAX = 24

WHISPER_THREADS = 2
WHISPER_NICE = 10
WHISPER_TIMEOUT_S = 30

WHISPER_GREEDY = True
WHISPER_NO_FALLBACK = True


LANGS = ("en", "ro", "zh")
LANG_NAMES = {"en": "English", "ro": "Română", "zh": "中文"}

SETTINGS_SEED = {
    "listening": True,
    "dry_run": False,
    "stt_lang": "auto",
    "stt_model": "",
    "mic_device": MIC_DEVICE,
    "mic_channel": 0,
    "gain": 4.0,
    "threshold": 600.0,
    "fuzz": 0.80,
    "camera": True,
}

MATCH_MARGIN = 0.15

GAIN_RANGE = (1.0, 32.0)
THRESHOLD_RANGE = (50.0, 8000.0)
FUZZ_RANGE = (0.50, 1.00)

VOICE_COOLDOWN_S = 1.5
TRANSCRIPT_MAX = 200

SETTINGS_FILE = "settings.json"
COMMANDS_FILE = "commands.json"

RECORD_DIR = "recordings"
RECORD_MAX_S = 300
RECORD_KEEP = 20
RECORD_QUEUE_CHUNKS = 400
MONITOR_QUEUE_CHUNKS = 16

COMMAND_SEED = [
    {
        "label": {"en": "Sit down", "ro": "Șezi", "zh": "坐下"},
        "phrases": {
            "en": ["sit down", "sit up", "suki sit"],
            "ro": ["șezi", "stai jos", "așează-te"],
            "zh": ["坐下", "坐好"],
        },
        "target": "seq:2",
    },
    {
        "label": {"en": "Stand up", "ro": "Ridică-te", "zh": "站起来"},
        "phrases": {
            "en": ["stand up", "get up", "suki stand"],
            "ro": ["ridică-te", "în picioare", "sus"],
            "zh": ["站起来", "起立"],
        },
        "target": "seq:1",
    },
    {
        "label": {"en": "Hold position", "ro": "Ține poziția", "zh": "保持姿势"},
        "phrases": {
            "en": ["hold position", "hold still", "engage the legs"],
            "ro": ["ține poziția", "stai așa", "blochează picioarele"],
            "zh": ["保持姿势", "别动"],
        },
        "target": "engage",
    },
    {
        "label": {"en": "Relax", "ro": "Relaxează-te", "zh": "放松"},
        "phrases": {
            "en": ["relax", "go limp", "let go"],
            "ro": ["relaxează-te", "lasă-te moale", "dă drumul"],
            "zh": ["放松", "松开"],
        },
        "target": "relax",
    },
    {
        "label": {"en": "Emergency stop", "ro": "Oprire de urgență", "zh": "急停"},
        "phrases": {
            "en": ["emergency stop", "suki stop now", "kill the motors"],
            "ro": ["oprire de urgență", "oprește tot", "taie motoarele"],
            "zh": ["急停", "紧急停止"],
        },
        "target": "estop",
    },
    {
        "label": {"en": "Start recording", "ro": "Începe înregistrarea",
                  "zh": "开始录音"},
        "phrases": {
            "en": ["start recording", "begin recording"],
            "ro": ["începe înregistrarea", "pornește înregistrarea"],
            "zh": ["开始录音", "开始录制"],
        },
        "target": "record_start",
    },
    {
        "label": {"en": "Stop recording", "ro": "Oprește înregistrarea",
                  "zh": "停止录音"},
        "phrases": {
            "en": ["stop recording", "end recording"],
            "ro": ["oprește înregistrarea", "termină înregistrarea"],
            "zh": ["停止录音", "结束录音"],
        },
        "target": "record_stop",
    },
]


_WALK_TAUGHT = {
    "forward": [
            {"thigh": 1730, "k": 1.0000, "dwell": 0.00},
            {"thigh": 1883, "k": 0.4255, "dwell": 0.00},
            {"thigh": 2060, "k": 0.3214, "dwell": 0.00},
            {"thigh": 2200, "k": 0.3046, "dwell": 0.00},
            {"thigh": 2339, "k": 0.2995, "dwell": 0.00},
            {"thigh": 2480, "k": 0.0000, "dwell": 0.00},
            {"thigh": 2480, "k": 0.4930, "dwell": 0.00},
            {"thigh": 2480, "k": 1.0000, "dwell": 0.00},
            {"thigh": 2316, "k": 0.9940, "dwell": 0.00},
            {"thigh": 2151, "k": 1.0000, "dwell": 0.00},
            {"thigh": 2014, "k": 1.0000, "dwell": 0.00},
            {"thigh": 1867, "k": 1.0000, "dwell": 0.00},
    ],
    "backward": [
            {"thigh": 1867, "k": 1.0000, "dwell": 0.00},
            {"thigh": 2014, "k": 1.0000, "dwell": 0.00},
            {"thigh": 2151, "k": 1.0000, "dwell": 0.00},
            {"thigh": 2313, "k": 1.0000, "dwell": 0.00},
            {"thigh": 2480, "k": 1.0000, "dwell": 0.00},
            {"thigh": 2480, "k": 0.4930, "dwell": 0.00},
            {"thigh": 2480, "k": 0.0000, "dwell": 0.00},
            {"thigh": 2339, "k": 0.2995, "dwell": 0.00},
            {"thigh": 2200, "k": 0.3046, "dwell": 0.00},
            {"thigh": 2060, "k": 0.3214, "dwell": 0.00},
            {"thigh": 1883, "k": 0.4255, "dwell": 0.00},
            {"thigh": 1730, "k": 1.0000, "dwell": 0.00},
    ],
}


def _vertical_us(leg):
    pts = JOINT_ANGLE_POINTS.get(CH.get((leg, THIGH)))
    if not pts or len(pts) < 2:
        return None
    lo, hi = min(pts, key=lambda p: p[1]), max(pts, key=lambda p: p[1])
    if abs(hi[1] - lo[1]) < 1e-9:
        return None
    t = (0.0 - lo[1]) / (hi[1] - lo[1])
    return lo[0] + t * (hi[0] - lo[0])


def _shifted(points, leg, src="FR"):
    a, b = _vertical_us(src), _vertical_us(leg)
    off = 0.0 if (a is None or b is None) else b - a
    return [{"thigh": int(round(max(SAFE_MIN_US, min(SAFE_MAX_US, p["thigh"] + off)))),
             "k": p["k"], "dwell": p["dwell"]} for p in points]


_WALK_STEP = {
    "FR": [
        {"thigh": 2315, "k": 0.3478, "dwell": 0.00},
        {"thigh": 2323, "k": 0.3406, "dwell": 0.00},
        {"thigh": 2331, "k": 0.3287, "dwell": 0.00},
        {"thigh": 2338, "k": 0.3137, "dwell": 0.00},
        {"thigh": 2345, "k": 0.2956, "dwell": 0.00},
        {"thigh": 2352, "k": 0.2745, "dwell": 0.00},
        {"thigh": 2359, "k": 0.2502, "dwell": 0.00},
        {"thigh": 2366, "k": 0.2229, "dwell": 0.00},
        {"thigh": 2372, "k": 0.1925, "dwell": 0.00},
        {"thigh": 2377, "k": 0.1590, "dwell": 0.00},
        {"thigh": 2383, "k": 0.1225, "dwell": 0.00},
        {"thigh": 2388, "k": 0.0828, "dwell": 0.00},
        {"thigh": 2393, "k": 0.0399, "dwell": 0.00},
        {"thigh": 2409, "k": 0.2670, "dwell": 0.00},
        {"thigh": 2389, "k": 0.4848, "dwell": 0.00},
        {"thigh": 2350, "k": 0.5791, "dwell": 0.00},
    ],
    "FL": [
        {"thigh": 2312, "k": 0.6365, "dwell": 0.00},
        {"thigh": 2320, "k": 0.6194, "dwell": 0.00},
        {"thigh": 2328, "k": 0.5974, "dwell": 0.00},
        {"thigh": 2335, "k": 0.5703, "dwell": 0.00},
        {"thigh": 2342, "k": 0.5381, "dwell": 0.00},
        {"thigh": 2349, "k": 0.5007, "dwell": 0.00},
        {"thigh": 2356, "k": 0.4583, "dwell": 0.00},
        {"thigh": 2363, "k": 0.4112, "dwell": 0.00},
        {"thigh": 2369, "k": 0.3598, "dwell": 0.00},
        {"thigh": 2374, "k": 0.3034, "dwell": 0.00},
        {"thigh": 2380, "k": 0.2418, "dwell": 0.00},
        {"thigh": 2385, "k": 0.1752, "dwell": 0.00},
        {"thigh": 2390, "k": 0.1033, "dwell": 0.00},
        {"thigh": 2406, "k": 0.4700, "dwell": 0.00},
        {"thigh": 2386, "k": 0.8314, "dwell": 0.00},
        {"thigh": 2347, "k": 0.9918, "dwell": 0.00},
    ],
    "BR": [
        {"thigh": 2143, "k": 0.7619, "dwell": 0.00},
        {"thigh": 2150, "k": 0.7551, "dwell": 0.00},
        {"thigh": 2157, "k": 0.7453, "dwell": 0.00},
        {"thigh": 2163, "k": 0.7326, "dwell": 0.00},
        {"thigh": 2169, "k": 0.7170, "dwell": 0.00},
        {"thigh": 2175, "k": 0.6987, "dwell": 0.00},
        {"thigh": 2181, "k": 0.6776, "dwell": 0.00},
        {"thigh": 2186, "k": 0.6539, "dwell": 0.00},
        {"thigh": 2192, "k": 0.6275, "dwell": 0.00},
        {"thigh": 2196, "k": 0.5985, "dwell": 0.00},
        {"thigh": 2201, "k": 0.5669, "dwell": 0.00},
        {"thigh": 2205, "k": 0.5327, "dwell": 0.00},
        {"thigh": 2209, "k": 0.4959, "dwell": 0.00},
        {"thigh": 2223, "k": 0.7095, "dwell": 0.00},
        {"thigh": 2207, "k": 0.9047, "dwell": 0.00},
        {"thigh": 2173, "k": 0.9950, "dwell": 0.00},
    ],
    "BL": [
        {"thigh": 2250, "k": 0.7517, "dwell": 0.00},
        {"thigh": 2261, "k": 0.7431, "dwell": 0.00},
        {"thigh": 2271, "k": 0.7313, "dwell": 0.00},
        {"thigh": 2281, "k": 0.7164, "dwell": 0.00},
        {"thigh": 2291, "k": 0.6984, "dwell": 0.00},
        {"thigh": 2301, "k": 0.6773, "dwell": 0.00},
        {"thigh": 2309, "k": 0.6532, "dwell": 0.00},
        {"thigh": 2318, "k": 0.6261, "dwell": 0.00},
        {"thigh": 2326, "k": 0.5960, "dwell": 0.00},
        {"thigh": 2334, "k": 0.5630, "dwell": 0.00},
        {"thigh": 2341, "k": 0.5271, "dwell": 0.00},
        {"thigh": 2348, "k": 0.4881, "dwell": 0.00},
        {"thigh": 2354, "k": 0.4462, "dwell": 0.00},
        {"thigh": 2376, "k": 0.6735, "dwell": 0.00},
        {"thigh": 2350, "k": 0.8955, "dwell": 0.00},
        {"thigh": 2297, "k": 0.9947, "dwell": 0.00},
    ],
}

WALK_SEED = [
    {
        "name": name,
        "colour": colour,
        "legs": {leg: _shifted(pts, leg) for leg in LEGS},
    }
    for name, colour in (("forward", "#a855f7"), ("backward", "#22d3ee"))
    for pts in [_WALK_TAUGHT[name]]
] + [
    {"name": "step", "colour": "#36d399",
     "legs": {leg: [dict(p) for p in _WALK_STEP[leg]] for leg in LEGS}},
    {"name": "step back", "colour": "#22d3ee",
     "legs": {leg: [dict(p) for p in reversed(_WALK_STEP[leg])] for leg in LEGS}},
]
