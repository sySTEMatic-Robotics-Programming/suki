# Suki

**Date**: 11.11.2026\
**Project lead**: Ana-Maria Acsinte\
**Team members**: Tomescu Vlad-Costin, Postelnicu Andrei

## Repository structure
```text
├── backend/            # Python server (FastAPI): motors, camera, AI, voice
│   ├── models/         # YOLO models (.pt)
│   ├── lab/            # Lab images and annotated results
│   └── test_*.py       # Tests (pytest)
├── frontend/           # Web interface (plain HTML/CSS/JS, no build step)
│   ├── css/
│   └── js/
├── requirements.txt    # Python dependencies
├── run.sh              # Starts the server on port 8000
├── setup_voice.sh      # Installs whisper.cpp + model and tests the microphone
└── README.md           # This file
```

## About the project
Suki is a quadruped robot dog driven by a Raspberry Pi. You control it from a web
page served directly by the Pi. Suki can see (YOLO object detection from a USB
webcam), hear (offline speech recognition with whisper.cpp), and walk using
hand-tuned gaits.

There's no cloud and no LLM involved. All of the AI runs locally on the Pi.

**Suki's main goal** is to become a **guide dog (service dog)** for blind and
visually impaired people, helping them get around the city on foot on their own.
The robot needs to spot cars, traffic signs, potholes and the color of traffic
lights, tell the person what's around them, and stop whenever it isn't safe to
cross. The current version is a lab prototype. What's still left to do is
described in [Future plans](#future-plans).

## Installation and usage

- SSH into the Raspberry Pi:\
    `ssh <user>@<pi-ip>`

- Install the dependencies:\
    `pip install -r requirements.txt`

- Install speech recognition (whisper.cpp + model, Raspberry Pi OS / Debian):\
    `./setup_voice.sh`

- Start the server, then open `http://<pi-ip>:8000` in a browser:\
    `./run.sh`

- Run the tests:\
    `cd backend && python3 -m pytest -q`

### SIM mode

Every piece of hardware is optional, so the interface runs on any laptop:

| Missing | What happens |
|---|---|
| PCA9685 / I2C libraries | Motors run in **SIM** mode and nothing is sent |
| whisper.cpp or its model | The Audio tab runs in SIM mode; typed text still triggers commands |
| Webcam | The video shows "NO CAMERA" and retries every 10 s |
| `ultralytics` / `torch` | Object detection is disabled; everything else works |

Set `SUKI_NO_CAMERA=1` to keep any camera from being opened.

### Libraries used

| Library | Used for |
|---|---|
| `fastapi`, `uvicorn`, `websockets` | Web server and WebSocket |
| `numpy` | Audio and image processing |
| `opencv-python` | Camera, drawing on frames, traffic light color |
| `adafruit-circuitpython-pca9685`, `adafruit-blinka` | I2C communication with the PCA9685 (robot only) |
| `ultralytics`, `torch` | YOLO (optional) |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp), `alsa-utils` (`arecord`) | Speech recognition and microphone capture. These aren't pip packages; `./setup_voice.sh` installs them |

## Software documentation

### Architecture
The backend is a **FastAPI + uvicorn** server written in Python. It drives the
motors, reads the camera and microphone, and runs the AI models. The frontend is
plain HTML/JS with no build step, served by the same server.

- Telemetry is pushed to the browser over the `/ws` WebSocket, 10 times per second.
- Video is streamed to the browser as MJPEG at `/stream.mjpg`.

### Modules

| File | What it does |
|---|---|
| `backend/app.py` | FastAPI server, routes, WebSocket |
| `backend/controller.py` | 50 Hz motion loop, engage/relax/E-STOP, poses |
| `backend/driver.py` | PCA9685 driver, chip verification, brownout protection |
| `backend/corridor.py` | Safe knee range for each thigh position |
| `backend/walk.py` | Gait points |
| `backend/sequence.py` | Pose sequences |
| `backend/camera.py` | USB webcam capture, MJPEG stream |
| `backend/vision.py` | YOLO detection + traffic light color |
| `backend/lab.py` | Offline test bench for models |
| `backend/audio.py` | Microphone capture, speech detection, recording |
| `backend/stt.py` | whisper.cpp bridge |
| `backend/voice.py` | Settings, voice commands, fuzzy matching |
| `backend/listener.py` | Listens for speech and triggers commands |
| `backend/config.py` | All constants: channels, limits, speeds, models |
| `frontend/` | Web interface (`index.html`, `js/`, `css/`) |

### Motor control

- **50 Hz motion loop.** A dedicated thread runs 50 times per second. When it's
  allowed to, it asks Linux for real-time priority (`SCHED_FIFO` 10).
- **Speed ramping.** Servos never jump straight to their target. Each tick they
  move toward it at a set speed: 900 µs/s by default, adjustable from 60 to
  2400 µs/s.
- **One I2C write per tick.** All 16 channels are sent to the PCA9685 in a single
  transaction. Every 0.1 s one channel is read back to confirm the chip is holding
  the value it was sent.
- **Leg corridor.** For every thigh position there's a safe min/max range for the
  knee (`backend/corridor.json`). Movements are clamped and broken into steps so
  the knee always stays inside that range. This keeps the leg from hitting itself
  or the body.
- **Pulsed motion.** Optional: the legs move one at a time, in steps of at most
  400 µs, so the battery never has to power all four legs moving at once.
- **Brownout protection.** The PCA9685 is checked every 0.2 s. A brownout resets
  the chip to the wrong PWM frequency. At the wrong frequency the pulses come out
  with the wrong width and can drive every joint past its limits. When this
  happens, Suki holds all outputs at zero and then sets the frequency again. If the
  chip is found reset 3 times within 6 s, Suki gives up and keeps all outputs off
  until a restart. This is a power supply problem: fix the supply.
- **E-STOP** sets all outputs to zero (the servos go limp). Press UNLOCK to take
  control of the robot again.

### Vision: YOLO

Suki uses [Ultralytics](https://docs.ultralytics.com) **YOLO26 nano** models.
The files live in `backend/models/`:

| Model | What it detects | Training |
|---|---|---|
| `yolo26n.pt` | 80 common COCO classes (person, car, dog, cat, traffic light…) | Standard COCO weights |
| `trafficeu.pt` | 55 European road signs (speed limits, stop, yield, pedestrian crossing…) | Fine-tuned from `yolo26n.pt`, 100 epochs, 640 px, on the "Traffic Signs Detection Europe v14" dataset (~4,500 images) |
| `trafficch.pt` | 4 types of Hong Kong signs (direction, mandatory, street direction, warning) | Fine-tuned from `yolo26n.pt`, 50 epochs, 640 px |

The live camera uses `yolo26n.pt`. To use a different model, change `YOLO_MODEL`
in `backend/config.py`.

#### How live detection works

1. The camera thread reads frames at 640×480, 20 fps.
2. A separate detection thread loads YOLO on first use, with `torch` limited to
   2 threads, and then does a warm-up run.
3. The detector grabs the latest frame and runs YOLO at **256 px** with a
   **confidence of 0.4**. It then waits 0.1 s and grabs the next latest frame. The
   camera never waits on YOLO: it just draws the most recent boxes it has.
4. Boxes are drawn on the video. These classes are drawn in orange as alerts:
   person, bicycle, car, motorcycle, bus, truck, cat, dog.
5. The video reaches the browser as MJPEG (`/stream.mjpg`). Detections are sent
   over the WebSocket.

#### Traffic light color

YOLO only finds *where* the traffic light is. The color is worked out with plain
OpenCV:

1. Take the largest `traffic light` box and crop it.
2. Convert the crop to HSV and count the red, yellow and green pixels.
3. If red or green covers at least 2% of the crop, that's the light's color.
4. If YOLO is off, the whole frame is checked instead.

The Lab uses a more robust version. When the pixel count is too weak, it looks for
the brightest spot in the crop, then checks its hue and its height within the
housing (red is at the top, green at the bottom).

#### Lab

The Vision tab includes a Lab for testing models on still images:

- Upload up to 60 images (12 MB max each, resized to 1280 px on the long side).
- Run any `.pt` file from `backend/models/` on them, with your choice of
  confidence and image size (160–1280 px).
- Annotated results are saved as `backend/lab/<id>__<model>.out.jpg`.
- At most 2 models are kept in memory at a time.

Any new `.pt` file dropped into `backend/models/` shows up in the Lab automatically.

### Voice: whisper.cpp

Speech recognition uses [whisper.cpp](https://github.com/ggerganov/whisper.cpp)
and runs fully offline. `./setup_voice.sh` builds it and downloads the model.

- **Model:** `ggml-base-q5_1.bin` by default. Other `.bin` models in the whisper
  models folder can be selected from the Audio tab.
- **Languages:** English, Romanian, Chinese, or auto-detect.
- **Speed settings:** greedy decoding, no fallback, 2 threads, `nice 10`, so the
  motion loop keeps priority.

How a voice command works:

1. `arecord` captures audio from the microphone at 16 kHz.
2. An energy threshold listens for loud sound. Speech starts when the level goes
   above the threshold and ends after 0.7 s of silence. Clips shorter than 0.4 s
   are ignored, and long ones are cut off at 8 s.
3. whisper.cpp transcribes the clip. Every command phrase is passed in as the
   prompt, so whisper favors the words Suki knows.
4. The text is lowercased and stripped of diacritics, then fuzzy-matched against
   every phrase of every command, in all languages.
5. A command fires if its score is at least 0.80 and beats the runner-up by 0.15.
   Otherwise the result is "no match" or "ambiguous". The same command can't fire
   again for 1.5 s.

Built-in commands (editable from the Audio tab, saved in `backend/commands.json`):

| Command | Example phrases |
|---|---|
| Sit down | "sit down", "șezi", "坐下" |
| Stand up | "stand up", "ridică-te", "站起来" |
| Hold position | "hold position", "ține poziția", "保持姿势" |
| Relax | "relax", "relaxează-te", "放松" |
| Emergency stop | "emergency stop", "oprire de urgență", "急停" |
| Start / stop recording | "start recording", "oprește înregistrarea" |

A command can trigger a pose, a sequence, engage, relax, E-STOP, or recording.

### Movement

- **Poses (Actions):** saved positions for all 8 leg servos, e.g. `SIT DOWN`,
  `P1`…`P5`. You can record the current position from the interface. Saved in
  `backend/actions.json`.
- **Sequences:** a chain of poses with a hold time, repeat count and optional
  reverse, e.g. "sit up" = `SIT DOWN → P1 → P2 → P3 → P4`. Saved in
  `backend/sequences.json`.
- **Gait points:** a gait is a list of points for each leg. Each point has a
  thigh position (µs), a knee position `k` (0 = bottom of the safe corridor,
  1 = top), and a pause time. Built-in gaits: `forward`, `backward`, `step`,
  `step back`. Saved in `backend/walk_points.json`.

### Web interface

Open it at `http://<pi-ip>:8000`.

| Tab | What it does |
|---|---|
| Drive | Walking joystick, pose buttons, live leg cards, fullscreen camera |
| Calibration | Servo table, leg limits/corridor, gait points, walk test, pulsed motion, poses, sequences |
| Simulator | 2D leg model showing the live position and gait arcs. Sends nothing to the robot |
| Vision | Live camera with detections, camera on/off, the Lab |
| Audio | Microphone level, listening settings, whisper model, recording, voice commands |
| Auto | Empty for now |

## Hardware documentation

### Mechanical systems
**CAD software**: Fusion

Suki has 4 legs, each with 3 joints: hip, thigh and knee.

| Dimension | Value |
|---|---|
| Upper leg segment | 107 mm |
| Lower leg segment | 138 mm |
| Body length | 230 mm |
| Body width | 78 mm |
| Standing height | 150 mm |

### Electrical systems
**CAD software:** Fusion

Bill of materials:

| Component | Details |
|---|---|
| Computer | Raspberry Pi (timings in the code were measured on a Pi 4) |
| Servo driver | PCA9685 board, 16 PWM channels, I2C bus 1, address `0x40`, 50 Hz |
| Motors | 12 standard PWM servos (500–2500 µs): 4 legs × (hip, thigh, knee) |
| Camera | USB webcam, 640×480 at 20 fps, via OpenCV/V4L2 |
| Microphone | The webcam's built-in mic (`plughw:CARD=Webcam,DEV=0`), 16 kHz |

Servo wiring to the PCA9685 channels (from `backend/config.py`):

| Leg | Thigh | Knee | Hip |
|---|---|---|---|
| Back-Left (BL) | ch 0 | ch 1 | ch 2 |
| Back-Right (BR) | ch 4 | ch 5 | ch 6 |
| Front-Left (FL) | ch 8 | ch 9 | ch 10 |
| Front-Right (FR) | ch 12 | ch 13 | ch 14 |

- The 4 hip servos are **disabled by default**. Suki moves using 8 servos (thighs
  and knees). The hips can be enabled under Calibration → Hardware table.
- Servo pulses range from 500 to 2500 µs, with neutral at 1500 µs. Each servo has
  its own min, max and invert settings, saved in `backend/servo_config.json`.

## Future plans

### Goal: a guide dog for blind people

The end goal is for Suki to walk a blind person down the street, the way a guide
dog does. Concretely, the robot needs to be able to:

- walk along the sidewalk in front of the person and guide them by a handle (harness);
- steer around obstacles: poles, people, bikes, cars parked on the sidewalk;
- stop at curbs, stairs and potholes;
- find pedestrian crossings and pedestrian signals;
- say when the light is green and only cross when it's safe;
- follow a route requested by voice ("take me to the pharmacy");
- **refuse a dangerous command** (e.g. "forward" when a car is coming). Real guide
  dogs do the same thing; it's called *intelligent disobedience*.

### Required improvements

#### Mechanics and power

| Now | What's needed |
|---|---|
| 150 mm tall, 230 mm body | A bigger robot (~50–60 cm tall), so it can be held by a handle and climb a 15 cm curb |
| Hobby PWM servos, hips disabled | Stronger motors (high-torque servos or geared BLDC motors), all 12 joints active |
| Hand-tuned gaits | Dynamic, balanced walking (IMU + closed-loop control) for uneven ground, slopes and snow |
| Brownout problems | A dedicated motor battery, separate from the computer, with at least 1–2 hours of runtime |
| No protection | A rain- and dust-resistant enclosure (IP54 or better) |
| — | A handle with a force sensor and vibration (haptic feedback), so the person can feel direction changes and stops |

#### Sensors

| Sensor | What for |
|---|---|
| Stereo / depth camera | Distance to obstacles, curbs and potholes. Computes depth in hardware without loading the main processor |
| Wide-angle camera, mounted higher | Traffic lights and signs are overhead; a camera 15 cm off the ground can't see them well |
| IMU (accelerometer + gyroscope) | Balance, fall detection, slope |
| Ultrasonic / ToF sensors | Very close obstacles, glass, things the camera misses |
| GPS (ideally RTK) + compass | Route navigation |
| Multi-capsule microphone array | Voice commands over street noise |
| Speaker / bone-conduction headset | Spoken messages that don't drown out street sounds |

#### Software

- **Auto tab**: this is where autonomous mode will go (it's empty for now).
- **Navigation**: offline OpenStreetMap maps, sidewalk routing, GPS + odometry
  localization.
- **Segmentation**: sidewalk, road, crosswalk, curb, stairs, not just bounding boxes.
- **Object tracking** (e.g. ByteTrack): the same car is followed from frame to
  frame, so Suki knows whether it's approaching and how fast.
- **Dedicated traffic light model**: the color is currently read with HSV
  thresholds, which get it wrong in strong sunlight, at night, or with
  reflections. This needs a trained classifier with the classes `red`, `green`,
  `yellow`, `off`, `unknown`, with separate handling for pedestrian signals (the
  little walking man) and vehicle lights. A "green" decision is only made after
  several consecutive frames agree.
- **Higher resolution**: detection currently runs at 256 px. At that resolution a
  traffic light 15 m away is only a few pixels. It needs 640 px or more.
- **Offline spoken messages (TTS)**: "car on the left", "crosswalk ahead",
  "green, we can cross".
- **Safety**: a watchdog, automatic stop when a sensor stops responding, and a
  complete log of every decision. The ground rule: **when in doubt, Suki stops**.

### High-accuracy recognition

What Suki needs to recognize, and the proposed targets:

| Class | Examples | Proposed target |
|---|---|---|
| Pedestrian signal + color | red, green, flashing green, off | ≥ 99% detection up to 20 m; false "green" virtually zero (under 1 in 10,000 decisions) |
| Vehicles | car, bus, truck, motorcycle, bicycle, scooter | ≥ 98% detection up to 30 m, latency under 150 ms |
| Pedestrians and animals | person, stroller, dog | ≥ 97% detection |
| Traffic signs | pedestrian crossing, stop, yield, no entry | mAP50 ≥ 0.90 |
| Ground hazards | potholes, missing manhole covers, curbs, stairs, uneven pavement, puddles | ≥ 95% detection up to 5 m |
| Navigation features | crosswalk (zebra), sidewalk, road | Segmentation, IoU ≥ 0.85 |

Not all errors are equal. Reading "red" as "green" can be fatal; reading "green"
as "red" just means waiting a bit longer. Models and thresholds are chosen to err
on the side of stopping.

Why latency matters: a car at 50 km/h covers ~14 m per second. With a 200 ms
delay, the car has already traveled almost 3 m by the time Suki reacts.

### Required datasets

**Public datasets** (for pre-training):

| Dataset | What it contains |
|---|---|
| [COCO](https://cocodataset.org) | People, vehicles, traffic lights (already used by `yolo26n.pt`) |
| [Mapillary Traffic Sign Dataset](https://www.mapillary.com/dataset/trafficsign) | Over 300 sign types from around the world, Europe included |
| [GTSDB / GTSRB](https://benchmark.ini.rub.de) | German traffic signs (similar to Romanian ones) |
| [DriveU Traffic Light Dataset (DTLD)](https://www.uni-ulm.de/in/iui-drive-u/projekte/driveu-traffic-light-dataset/) | Traffic lights from German cities, each labeled with its state |
| Pedestrian Traffic Lights (PTL / LYTNet) | Pedestrian signals photographed from a pedestrian's point of view, built for blind users |
| [Mapillary Vistas](https://www.mapillary.com/dataset/vistas) / [Cityscapes](https://www.cityscapes-dataset.com) | Street segmentation: sidewalk, curb, crosswalk |
| [RDD2022](https://github.com/sekilab/RoadDamageDetector) | Potholes and cracks in asphalt, from several countries |
| [BDD100K](https://www.vis.xyz/bdd100k/) | Tough conditions: night, rain, fog |

**Our own dataset** (required): public datasets are shot from cars, at driver
eye level. Suki sees the street from low down on the sidewalk, and Romanian
traffic lights, signs and crosswalks look a little different. We need:

- footage shot with the robot's own camera, at its height, on Romanian sidewalks;
- every condition: day, night, rain, snow, sun in front, backlighting;
- Romanian pedestrian signals, including the ones with countdown timers;
- potholes, manhole covers, curbs and stairs on sidewalks, not just on the road;
- roughly **≥ 1,500 images and ≥ 10,000 annotated objects per class**
  (Ultralytics' recommendation), plus ~10% background images with no objects;
- annotation with [CVAT](https://www.cvat.ai) or [Label Studio](https://labelstud.io),
  reviewed by two people for the critical classes (traffic lights, vehicles).

Final testing is done on a separate set, shot on streets the model has never seen.

### Required compute

**Which metric matters**

- **INT8 TOPS** (tera-operations per second at 8-bit): the main metric. YOLO
  models can run 8-bit quantized with almost no loss in accuracy.
- **FP16/FP32 TFLOPS**: only relevant if the models run unquantized.
- The number on the spec sheet is a theoretical peak. A real model usually uses
  only 20–40% of it.
- What actually matters: **frames per second and latency measured on our model,
  at our resolution**, plus **TOPS/W**, since the robot runs on battery.

**How much compute is needed**

| Task | Example model | Cost per frame | Target fps |
|---|---|---|---|
| Vehicle, pedestrian and sign detection (640 px) | YOLO26s | ~20 GFLOPs | 15–20 |
| Sidewalk, crosswalk and pothole segmentation (640 px) | YOLO26s-seg | ~30–40 GFLOPs | 10 |
| Traffic light color classification (on the crop) | Small CNN | < 1 GFLOP | 15–20 |
| Depth | Computed by the stereo camera | 0 on the main processor | 30 |

Total: ~0.7–1 TOPS of actual use. Accounting for 20–40% real-world utilization
and headroom for bigger models, that means **at least ~13 INT8 TOPS, with 26 TOPS
or more recommended**.

**Current hardware vs. what's needed**

| Metric | Now (Raspberry Pi 4, CPU only) | Needed for the street |
|---|---|---|
| AI compute | under 0.05 FP32 TFLOPS (theoretical peak, 4 Cortex-A72 cores), no accelerator | ≥ 13 INT8 TOPS, ≥ 26 TOPS recommended |
| Detection resolution | 256 px | ≥ 640 px |
| Model | YOLO26 nano (~6 GFLOPs at 640 px, ~1 GFLOP at 256 px) | "Small" model or larger (~20–40 GFLOPs), several models in parallel |
| Detection fps | a few, with a 0.1 s pause between runs | ≥ 15 for detection, ≥ 10 for segmentation |
| Camera → decision latency | hundreds of ms | under 150 ms |
| RAM | shared with the rest of the system | ≥ 8 GB |
| AI power draw | — | under ~15 W, so the battery lasts 1–2 hours |

On the Pi 4's CPU, YOLO nano at 640 px only manages a few frames per second.
That's why detection currently runs at 256 px with pauses. For street use,
compute needs to go up by a factor of several hundred.

**Energy efficiency: why an AI accelerator**

Suki runs on batteries and, like a guide dog, has to last a full walk across
town. Battery life matters just as much as compute. A dedicated AI accelerator
(NPU) helps directly with this:

- An NPU performs the same operations as the CPU using far less energy. A
  general-purpose CPU typically gets under 0.01 TOPS/W on neural networks. An NPU
  reaches a few TOPS/W, making it hundreds of times more efficient per frame.
- A Pi 4 CPU running YOLO nonstop sits near full load: it draws more power, heats
  up and ends up throttling itself. With an accelerator, the CPU stays free for
  the 50 Hz motion loop, voice and navigation.
- The energy saved on compute goes to the motors, which use the most power
  anyway. That means more kilometers per charge.
- The target is for all of the AI to draw **under ~15 W**, at **≥ 2 TOPS/W**.

---
**© sySTEMatic Robotics**
