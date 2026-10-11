import asyncio
import contextlib
import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (JSONResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles

import audio
import config
from camera import CameraStreamer
from lab import Lab
from controller import Controller, _write_json
from listener import Listener
from sequence import SequenceStore
from sketch import SketchStore
from vision import VisionProcessor
from voice import BUILTIN_TARGETS, CommandStore, Settings
from walk import WalkStore

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(HERE, "..", "frontend")
RECORD_DIR = os.path.join(HERE, config.RECORD_DIR)
os.makedirs(RECORD_DIR, exist_ok=True)

robot: Controller
detector: VisionProcessor
camera: CameraStreamer
settings: Settings
commands: CommandStore
listener: Listener
recorder: audio.Recorder
walkpoints: WalkStore
sketches: SketchStore
sequences: SequenceStore
lab: Lab


class ConnectionManager:

    def __init__(self):
        self._conns = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._conns[ws] = asyncio.Queue(maxsize=4)

    def disconnect(self, ws: WebSocket):
        self._conns.pop(ws, None)

    async def writer(self, ws: WebSocket):
        q = self._conns[ws]
        try:
            while True:
                await ws.send_json(await q.get())
        except Exception:
            pass

    def send(self, ws: WebSocket, msg):
        q = self._conns.get(ws)
        if q is None:
            return
        if q.full():
            with contextlib.suppress(Exception):
                q.get_nowait()
        with contextlib.suppress(Exception):
            q.put_nowait(msg)

    def broadcast(self, msg):
        for ws in list(self._conns):
            self.send(ws, msg)


manager = ConnectionManager()


def build_telemetry():
    state = robot.get_state()
    state["type"] = "telemetry"
    state["camera"] = camera.state()
    state["vision"] = dict(camera.results or {})
    state["vision"].setdefault("traffic_enabled", bool(detector.enable_traffic))
    state["vision"].setdefault("objects_enabled", bool(detector.enable_objects))
    state["vision"].setdefault("model", config.YOLO_MODEL)
    state["voice"] = listener.get_state()
    state["voice"]["recorder"] = recorder.state()
    state["voice"]["targets"] = dict(BUILTIN_TARGETS)
    state["walk"] = walkpoints.public()
    state["sketch"] = sketches.public()
    state["seq"] = sequences.public()
    state["lab"] = lab.public()
    return state


async def telemetry_loop():
    period = 1.0 / config.TELEMETRY_HZ
    save_every = max(1, int(config.TELEMETRY_HZ * 2))
    n = 0
    while True:
        try:
            state = build_telemetry()
            sequences.tick(state, robot.action_run)
            state["seq"] = sequences.public()
            manager.broadcast(state)
            n += 1
            if n % save_every == 0:
                walkpoints.flush()
                sketches.flush()
                sequences.flush()
        except Exception as e:
            print("[telemetry] %s" % e)
        await asyncio.sleep(period)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    global robot, detector, camera, settings, commands, listener, recorder, walkpoints
    global lab, sketches, sequences
    robot = Controller()
    settings = Settings(os.path.join(HERE, config.SETTINGS_FILE))
    commands = CommandStore(os.path.join(HERE, config.COMMANDS_FILE))
    walkpoints = WalkStore(os.path.join(HERE, config.WALK_FILE), _write_json)
    sketches = SketchStore(os.path.join(HERE, config.SKETCH_FILE), _write_json)
    sequences = SequenceStore(os.path.join(HERE, config.SEQ_FILE), _write_json,
                              robot.actions)
    lab = Lab(HERE, _write_json)
    detector = VisionProcessor()
    camera = CameraStreamer(vision=detector, settings=settings)
    listener = Listener(settings, commands, robot=robot, sequences=sequences)
    recorder = audio.Recorder(listener.mic, RECORD_DIR)
    listener.recorder = recorder
    print("[suki] voice %s | mic %s | stt %s"
          % (listener.mode, listener.mic.error or "ok", listener.stt.error or "ok"))
    task = asyncio.create_task(telemetry_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        walkpoints.flush()
        sketches.flush()
        sequences.stop("stopped: the program is shutting down")
        sequences.flush()
        lab.shutdown()
        recorder.stop()
        listener.shutdown()
        camera.shutdown()
        detector.shutdown()
        robot.shutdown()


app = FastAPI(lifespan=lifespan)


def handle(cmd):
    t = cmd.get("type")

    if t == "ping":
        return
    robot.log.cmd(t or "?", **{k: v for k, v in cmd.items() if k != "type"})

    if t == "leg_pair":
        robot.set_leg_pair(str(cmd.get("leg", "")),
                           thigh_us=cmd.get("thigh"), knee_us=cmd.get("knee"))
    elif t == "servo":
        robot.set_servo(cmd.get("ch"), cmd.get("us"))
    elif t == "servo_config":
        robot.set_servo_config(cmd.get("ch"), invert=cmd.get("invert"),
                               enabled=cmd.get("enabled"),
                               min_us=cmd.get("min"), max_us=cmd.get("max"))
    elif t == "channel_map":
        robot.set_channel_slot(cmd.get("ch"), cmd.get("leg"), cmd.get("joint"))
    elif t == "test_mode":
        robot.set_test_mode(cmd.get("on"))
    elif t == "servo_test":
        robot.set_test_us(cmd.get("ch"), cmd.get("us"))
    elif t == "speed":
        robot.set_speed(cmd.get("value"))
    elif t == "pulse":
        robot.set_pulse(us=cmd.get("us"), delay_ms=cmd.get("delay_ms"))
    elif t == "engage":
        robot.engage(cmd.get("leg"))
    elif t == "relax":
        sequences.stop("stopped: the legs were relaxed")
        robot.relax(cmd.get("leg"))
    elif t == "estop":
        sequences.stop("stopped by E-STOP")
        robot.estop()
    elif t == "clear_estop":
        robot.clear_estop()
    elif t == "corridor_point":
        robot.set_corridor_point(str(cmd.get("leg", "")), cmd.get("index"),
                                 drive=cmd.get("drive"), min_us=cmd.get("min"),
                                 max_us=cmd.get("max"))
    elif t == "corridor_add":
        robot.add_corridor_point(str(cmd.get("leg", "")), cmd.get("drive"))
    elif t == "corridor_delete":
        robot.delete_corridor_point(str(cmd.get("leg", "")), cmd.get("index"))
    elif t == "return_to_last":
        robot.return_to_last()
    elif t == "action_run":
        robot.action_run(cmd.get("id"))
    elif t == "action_record":
        robot.action_record(cmd.get("name"))
    elif t == "action_rename":
        robot.actions.rename(cmd.get("id"), cmd.get("name"))
    elif t == "action_set":
        robot.actions.set_channel(cmd.get("id"), cmd.get("ch"), cmd.get("us"))
    elif t == "action_delete":
        robot.actions.delete(cmd.get("id"))
    elif t == "walk_set_add":
        walkpoints.add_set(cmd.get("name"), copy_of=cmd.get("copy_of"))
    elif t == "walk_set_rename":
        walkpoints.rename_set(cmd.get("id"), cmd.get("name"))
    elif t == "walk_set_colour":
        walkpoints.recolour_set(cmd.get("id"), cmd.get("colour"))
    elif t == "walk_set_delete":
        walkpoints.delete_set(cmd.get("id"))
    elif t == "walk_add":
        walkpoints.add_point(cmd.get("set"), str(cmd.get("leg", "")),
                             cmd.get("thigh"), cmd.get("k"), index=cmd.get("index"))
    elif t == "walk_set_point":
        walkpoints.set_point(cmd.get("set"), str(cmd.get("leg", "")), cmd.get("index"),
                             thigh=cmd.get("thigh"), k=cmd.get("k"),
                             dwell=cmd.get("dwell"))
    elif t == "walk_delete":
        walkpoints.delete_point(cmd.get("set"), str(cmd.get("leg", "")),
                                cmd.get("index"))
    elif t == "walk_move":
        walkpoints.move_point(cmd.get("set"), str(cmd.get("leg", "")),
                              cmd.get("index"), cmd.get("delta"))
    elif t == "walk_clear":
        walkpoints.clear(cmd.get("set"), str(cmd.get("leg", "")))
    elif t == "walk_copy_leg":
        walkpoints.copy_leg(cmd.get("set"), str(cmd.get("from", "")),
                            str(cmd.get("to", "")))
    elif t == "seq_add":
        sequences.add()
    elif t == "seq_rename":
        sequences.rename(cmd.get("id"), cmd.get("name"))
    elif t == "seq_opts":
        sequences.set_opts(cmd.get("id"), reverse=cmd.get("reverse"),
                           repeat=cmd.get("repeat"), hold=cmd.get("hold"))
    elif t == "seq_delete":
        sequences.delete(cmd.get("id"))
    elif t == "seq_step_add":
        sequences.add_step(cmd.get("id"), cmd.get("action"))
    elif t == "seq_step_del":
        sequences.del_step(cmd.get("id"), cmd.get("index"))
    elif t == "seq_run":
        sequences.start(cmd.get("id"), robot.get_state())
    elif t == "seq_stop":
        sequences.stop()
    elif t == "sketch_add":
        sketches.add(str(cmd.get("leg", "")), cmd.get("stroke"))
    elif t == "sketch_undo":
        sketches.undo(str(cmd.get("leg", "")))
    elif t == "sketch_erase":
        sketches.erase(str(cmd.get("leg", "")), cmd.get("index"))
    elif t == "sketch_clear":
        sketches.clear(str(cmd.get("leg", "")) or None)
    elif t == "lab_run":
        lab.enqueue(cmd.get("image"), cmd.get("models"), cmd.get("conf"),
                    cmd.get("imgsz"))
    elif t == "lab_delete":
        lab.delete(cmd.get("image"))
    elif t == "lab_clear":
        lab.clear_runs(str(cmd.get("image", "")))
    elif t == "lab_capture":
        jpg = camera.latest_jpeg()
        if jpg:
            lab.add(jpg, name=str(cmd.get("name") or "camera"))
    elif t == "vision":
        detector.set_options(enable_traffic=cmd.get("traffic"),
                             enable_objects=cmd.get("objects"),
                             conf=cmd.get("conf"))
    elif t == "setting":
        settings.set(str(cmd.get("key", "")), cmd.get("value"))
    elif t == "refresh_devices":
        listener.mic.refresh()
    elif t == "vcommand_add":
        commands.add()
    elif t == "vcommand_set":
        commands.update(cmd.get("id"), str(cmd.get("field", "")),
                        cmd.get("value"), lang=cmd.get("lang"))
    elif t == "vcommand_delete":
        commands.delete(cmd.get("id"))
    elif t == "vcommand_run":
        listener.run_now(cmd.get("id"))
    elif t == "simulate":
        text = str(cmd.get("text") or "").strip()
        if text:
            listener.hear(text, source="typed")
    elif t == "record":
        on = cmd.get("on")
        if on is None:
            recorder.toggle()
        elif on:
            recorder.start()
        else:
            recorder.stop()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    writer = asyncio.create_task(manager.writer(ws))
    manager.send(ws, build_telemetry())
    try:
        while True:
            cmd = await ws.receive_json()
            try:
                handle(cmd)
            except Exception as e:
                print("[ws] command failed (%s): %s" % (cmd.get("type"), e))
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        writer.cancel()
        manager.disconnect(ws)


@app.get("/stream.mjpg")
def stream():
    return StreamingResponse(camera.mjpeg_generator(),
                             media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/snapshot.jpg")
def snapshot():
    return Response(camera.latest_jpeg(), media_type="image/jpeg")


_STREAM_BYTES = 0x7FFFFF00


@app.get("/audio.wav")
async def audio_live(request: Request):
    mic = listener.mic
    if not mic.available:
        return Response("no capture device on this machine (SIM)", status_code=503,
                        media_type="text/plain")

    async def frames():
        tap = mic.tap(config.MONITOR_QUEUE_CHUNKS)
        try:
            yield audio.wav_header(_STREAM_BYTES)
            while listener.alive and not await request.is_disconnected():
                if tap:
                    while tap:
                        yield tap.popleft().tobytes()
                else:
                    await asyncio.sleep(0.02)
        finally:
            mic.untap(tap)

    return StreamingResponse(frames(), media_type="audio/wav", headers={
        "Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/api/state")
def api_state():
    return build_telemetry()


@app.get("/api/geometry")
def api_geometry():
    ch_leg = {ch: (leg, joint) for ch, (leg, joint, _l) in config.SERVOS.items()}
    poses = []
    for p in config.VERIFIED_POSES:
        row = {}
        for ch, us in p["pos"].items():
            if ch in ch_leg and ch in config.JOINT_ANGLE_POINTS:
                leg, joint = ch_leg[ch]
                row.setdefault(leg, {})[joint] = us
        poses.append({"name": p["name"], "legs": row})

    return {
        "build": config.BUILD_TAG,
        "leg": config.LEG_GEOMETRY,
        "poses": poses,
        "angles": {
            "%s|%s" % (leg, joint): {
                "points": [list(p) for p in config.JOINT_ANGLE_POINTS[ch]],
                "provisional": ch in config.ANGLE_PROVISIONAL,
            }
            for ch, (leg, joint, _lbl) in config.SERVOS.items()
            if ch in config.JOINT_ANGLE_POINTS
        },
    }


@app.post("/api/lab/upload")
async def lab_upload(request: Request, name: str = ""):
    rec, err = lab.add(await request.body(), name=name)
    if not rec:
        return {"error": err or "rejected", "name": name}
    return {"added": rec}


@app.get("/api/lab/dets")
def lab_dets(image: str = ""):
    return lab.detections(image)


@app.get("/api/lab/export")
def lab_export(image: str = ""):
    data = lab.export(image)
    if data is None:
        return JSONResponse({"error": "no such picture"}, status_code=404)
    name = str(data["image"].get("name") or image).replace('"', "")
    return JSONResponse(data, headers={
        "Content-Disposition": 'attachment; filename="%s.analysis.json"' % name})


@app.get("/api/log")
def api_log(n: int = 200, level: str = ""):
    return {"entries": robot.log.tail(max(1, min(5000, n)), level or None)}


@app.get("/api/transcript")
def api_transcript(n: int = 200):
    return {"entries": listener.tail(max(1, min(config.TRANSCRIPT_MAX, n)))}


app.mount("/rec", StaticFiles(directory=RECORD_DIR), name="recordings")

os.makedirs(os.path.join(HERE, config.LAB_DIR), exist_ok=True)
app.mount("/lab", StaticFiles(directory=os.path.join(HERE, config.LAB_DIR)), name="lab")

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
