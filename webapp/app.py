"""Small web UI around host/tx_dvbs.py: pick a picture, symbol rate, FEC and level, then Start/Stop.

Fixed on purpose: 2405.000 MHz, DVB-S2 QPSK, no PA (--pa-enable is never passed), localhost only.
Run:  .venv-host\\Scripts\\python.exe webapp\\app.py   then open http://127.0.0.1:5000
"""
import atexit
import collections
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory, stream_with_context

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
import bandplan  # noqa: E402
import camera  # noqa: E402
import paths  # noqa: E402
import qo100_enc  # noqa: E402
import clap_test  # noqa: E402
import flasher  # noqa: E402
import version  # noqa: E402

PICTURES = Path(os.environ.get("DATV_PICTURES", paths.DATA / "pictures"))
VIDEOS = paths.DATA / "videos"
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".ts", ".m4v"}
CONFIG = paths.DATA / "config.json"                    # remembered board: {"port": "COM4", "serial": "<USB serial number>"}
FREQ_DEFAULT = "2405.000"                           # uplink MHz until you choose another
FREQ_MIN, FREQ_MAX = 2300.0, 2450.0                 # the firmware refuses anything outside; the whole signal must fit
SYMBOL_RATES = (125000, 250000, 333000, 500000, 1000000)
FECS = ("1/2", "3/5", "2/3", "3/4", "4/5")      # lower FEC: less signal needed (small dishes), less bitrate; the default stays 3/4
LEVEL_HARD_MIN, LEVEL_HARD_MAX = 1, 480            # the firmware's own range; zero is never sent (the firmware would pick a strong automatic level)
LEVEL_LIMITS_DEFAULT = (15, 100)                    # each user sets their own lowest and highest level on the Setup page
MAX_SECONDS = 3600                                  # safety cap: a forgotten tab cannot transmit forever
EXTS = {".png", ".jpg", ".jpeg"}

app = Flask(__name__, template_folder=str(paths.RESOURCE / "templates"), static_folder=str(paths.RESOURCE / "static"))
lock = threading.Lock()
conn = {"connected": False, "port": "", "serial": "", "info": "", "how": "", "candidates": [], "tried": []}
tx = {"state": "idle", "proc": None, "t0": 0.0, "log": collections.deque(maxlen=60),
      "error": "", "buffer": "", "packets": "", "stopping": False, "settings": None}
flash = {"state": "idle", "port": "", "log": collections.deque(maxlen=40), "percent": 0, "error": "", "result": ""}


def probe(port):
    """Send the read-only INFO query; return the firmware's ESP32DATV line or ''. DTR/RTS stay low so the C3 is not reset."""
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 115200, 0.2
    s.dtr = s.rts = False
    try:
        s.open()
        buf = b""
        for _ in range(3):
            s.write(b"\nINFO\n")
            t0 = time.time()
            while time.time() - t0 < 0.6 and b"ESP32DATV " not in buf:
                buf += s.read(256)
            if b"ESP32DATV " in buf:
                break
        line = next((l for l in buf.decode(errors="replace").splitlines() if l.startswith("ESP32DATV ")), "")
        return line
    except (serial.SerialException, OSError):
        return ""
    finally:
        s.close()


def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def write_config(**changes):
    """Merge into config.json (board and setup values live together); a None value removes the key."""
    cfg = load_config()
    for k, v in changes.items():
        if v is None:
            cfg.pop(k, None)
        else:
            cfg[k] = v
    CONFIG.write_text(json.dumps(cfg, indent=2))


def save_config(port, serial_number):
    write_config(port=port, serial=serial_number)


SETUP_DEFAULTS = {"callsign": "NOCALL", "locator": "JNxxyy", "clock_ahead": 5.0,
                  "level_min": LEVEL_LIMITS_DEFAULT[0], "level_max": LEVEL_LIMITS_DEFAULT[1]}      # a fresh install: everyone sets their own on the Setup page


def get_setup():
    cfg = load_config()
    return {k: cfg.get(k, v) for k, v in SETUP_DEFAULTS.items()}


def whole(value):
    """A whole number from a number or text; 15.5 is refused, not cut to 15."""
    number = float(value)
    if not number.is_integer():
        raise ValueError("not a whole number")
    return int(number)


def level_limits():
    """(lowest, highest) output level this user allows, from the Setup page. Levels below about 15 show a spike in the middle of the
    signal; above about 250 it is distorted. Bad values in config.json fall back to the defaults."""
    setup = get_setup()
    try:
        lo, hi = whole(setup["level_min"]), whole(setup["level_max"])
    except (TypeError, ValueError):
        return LEVEL_LIMITS_DEFAULT
    return (lo, hi) if LEVEL_HARD_MIN <= lo <= hi <= LEVEL_HARD_MAX else LEVEL_LIMITS_DEFAULT


def setup_ready():
    """False while callsign or locator are still the fresh-install placeholders: nobody transmits as NOCALL."""
    setup = get_setup()
    return (setup["callsign"].strip().upper() not in ("", SETUP_DEFAULTS["callsign"])
            and setup["locator"].strip().lower() != SETUP_DEFAULTS["locator"].lower())


def get_freq():
    return load_config().get("freq", FREQ_DEFAULT)


def check_freq(value, sr):
    """(uplink MHz as text with 3 decimals, error). The signal is about 1.35 x the symbol rate wide and must fit inside the band."""
    try:
        f = round(float(str(value).strip().replace(",", ".")), 3)
    except ValueError:
        return None, "frequency must be a number in MHz"
    half = sr * 1.35 / 2e6                              # MHz
    if not FREQ_MIN + half <= f <= FREQ_MAX - half:
        return None, f"frequency must be {FREQ_MIN + half:.3f} to {FREQ_MAX - half:.3f} MHz at this symbol rate"
    return f"{f:.3f}", ""


def check_setup(d):
    """Return (clean values, error text). Callsign and locator end up on the card, so keep them to plain characters."""
    callsign = str(d.get("callsign", "")).strip().upper()
    locator = str(d.get("locator", "")).strip()
    try:
        ahead = float(d.get("clock_ahead"))
    except (TypeError, ValueError):
        return None, "lead time must be a number"
    if not re.fullmatch(r"[A-Z0-9/]{3,12}", callsign):
        return None, "callsign: 3-12 letters, digits or /"
    if not re.fullmatch(r"[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2}([0-9]{2})?)?", locator):
        return None, "locator: like JN36 or JN36kl"
    if not 0 <= ahead <= 30:
        return None, "lead time: 0 to 30 seconds"
    return {"callsign": callsign, "locator": locator[:2].upper() + locator[2:4] + locator[4:6].lower() + locator[6:], "clock_ahead": ahead}, ""


def check_limits(d):
    """(lowest, highest, error) for the output level limits popup."""
    try:
        lo, hi = whole(d.get("level_min")), whole(d.get("level_max"))
    except (TypeError, ValueError):
        return None, None, "output level limits must be whole numbers"
    if not LEVEL_HARD_MIN <= lo <= hi <= LEVEL_HARD_MAX:
        return None, None, f"output level limits: {LEVEL_HARD_MIN} to {LEVEL_HARD_MAX}, and the lowest must not be above the highest"
    return lo, hi, ""


def espressif_ports():
    """Only Espressif native-USB ports (VID 303A) are ever touched: other COM ports may be radios or Bluetooth."""
    from serial.tools import list_ports
    return {p.device: p.serial_number or "" for p in list_ports.comports() if p.vid == 0x303A}


def found(port, serial_number, info, how):
    return {"connected": True, "port": port, "serial": serial_number, "info": info, "how": how, "candidates": []}


def find_esp():
    """1) saved port  2) saved USB serial number on whatever COM it has now  3) scan every Espressif port.
    One answering board is saved to config.json; several are returned as candidates for the user to choose."""
    ports = espressif_ports()
    cfg = load_config()
    tried = []
    saved_port, saved_serial = cfg.get("port"), cfg.get("serial")
    if saved_port in ports and (not saved_serial or ports[saved_port] == saved_serial):
        tried.append(saved_port)
        info = probe(saved_port)
        if info:
            return found(saved_port, ports[saved_port], info, "saved port")
    if saved_serial:
        for port, ser in ports.items():
            if ser == saved_serial and port not in tried:
                tried.append(port)
                info = probe(port)
                if info:
                    save_config(port, ser)
                    return found(port, ser, info, "saved serial number, new port")
    answering = []
    for port, ser in ports.items():
        if port in tried:                       # already probed above and did not answer
            continue
        info = probe(port)
        if info:
            answering.append({"port": port, "serial": ser, "info": info})
    if len(answering) == 1:
        a = answering[0]
        save_config(a["port"], a["serial"])
        return found(a["port"], a["serial"], a["info"], "scan, saved")
    missing = bool(saved_serial) and saved_serial not in ports.values()
    return {"connected": False, "port": "", "serial": "", "info": "", "how": "", "candidates": answering,
            "tried": sorted(ports), "saved": {"port": saved_port, "serial": saved_serial} if saved_serial else None,
            "saved_missing": missing}


def list_videos():
    VIDEOS.mkdir(parents=True, exist_ok=True)
    return sorted(p.name for p in VIDEOS.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in VIDEO_EXTS)


@app.get("/api/videos")
def api_videos():
    return jsonify(list_videos())


@app.get("/api/video-info")
def api_video_info():
    """A plain-words description of the chosen video, and a warning when it is too heavy to decode live."""
    name = request.args.get("name", "")
    if name not in list_videos():
        abort(404)
    from stream_tx import video_info
    try:
        return jsonify(video_info(VIDEOS / name))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.get("/videos/<path:name>")
def video_file(name):
    if name not in list_videos():
        abort(404)
    return send_from_directory(VIDEOS, name, conditional=True)


def list_pictures():
    PICTURES.mkdir(parents=True, exist_ok=True)
    return sorted(p.name for p in PICTURES.iterdir() if p.suffix.lower() in EXTS and p.is_file())


def reader(proc):
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        with lock:
            tx["log"].append(line)
            m = re.search(r"ESP buffer (\d+)\.\.(\d+) pairs, TS packets: (\d+) from the source, (\d+) null", line)
            if m:
                tx["buffer"] = f"{m.group(1)}..{m.group(2)} pairs"
                tx["packets"] = f"{m.group(3)} picture / {m.group(4)} null"
            elif line.startswith("OK QPSKT") and tx["state"] == "starting":
                tx["state"] = "transmitting"
                tx["t0"] = time.time()
            elif line.startswith("ERR") or "Traceback" in line:
                tx["error"] = line
    rc = proc.wait()
    with lock:
        if rc and not tx["stopping"] and not tx["error"]:
            tx["error"] = f"transmitter exited with code {rc}"
        tx["state"] = "error" if tx["error"] and not tx["stopping"] else "idle"
        tx["proc"] = None
        tx["stopping"] = False


def stop_tx(wait=10.0):
    with lock:
        proc = tx["proc"]
        if proc is None:
            return False
        tx["stopping"] = True
        tx["state"] = "stopping"
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        proc.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    except OSError:
        pass
    return True


atexit.register(stop_tx, 5.0)
atexit.register(camera.stop_previews)


@app.context_processor
def inject_version():
    return {"app_name": version.APP_NAME, "app_version": version.__version__}


@app.before_request
def same_origin_only():
    """Only this page may drive the transmitter: block cross-site requests to localhost."""
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] != request.host:
            abort(403)
        if not request.is_json:
            abort(415)


@app.before_request
def page_seen():
    """Any request from a page counts as 'someone is looking' (the page polls /api/status every second)."""
    if request.path != "/api/bye":
        WATCH["seen"] = time.time()


@app.post("/api/bye")
def api_bye():
    """The page is closing (pagehide). A reload or the Setup link comes back within seconds and cancels this."""
    WATCH["bye"] = time.time()
    return "", 204


@app.get("/")
def index():
    return render_template("index.html", rates=SYMBOL_RATES, fecs=FECS, freq=get_freq(),
                           lmin=0, lmax=level_limits()[1], ldef=0, level_min=level_limits()[0], max_seconds=MAX_SECONDS,
                           setup_ready=setup_ready())


@app.get("/pictures/<path:name>")
def picture(name):
    if name not in list_pictures():
        abort(404)
    return send_from_directory(PICTURES, name)


@app.get("/api/connection")
def api_connection():
    """Check for the board. Not while a transmission owns the port; the result of the last check is returned then."""
    with lock:
        if tx["proc"] is not None or tx["state"] in ("starting", "stopping") or flash["state"] == "flashing":
            return jsonify(**conn, busy=True)
    result = find_esp()
    with lock:
        conn.update({"tried": [], **result})
    return jsonify(**{"tried": [], **result}, busy=False)


@app.post("/api/connection/choose")
def api_connection_choose():
    """Several boards answered: the user picks one; it is probed again, then remembered."""
    port = (request.get_json(silent=True) or {}).get("port", "")
    ports = espressif_ports()
    if port not in ports:
        return jsonify(error="not an Espressif port"), 400
    info = probe(port)
    if not info:
        return jsonify(error="no answer from that port"), 409
    save_config(port, ports[port])
    with lock:
        conn.update({"tried": [], **found(port, ports[port], info, "chosen, saved")})
    return jsonify(ok=True)


@app.post("/api/connection/forget")
def api_connection_forget():
    """Setup page: drop the remembered board so the next check scans again."""
    with lock:
        if tx["proc"] is not None or tx["state"] in ("starting", "stopping"):
            return jsonify(error="stop the transmission first"), 409
        conn.update({"connected": False, "port": "", "serial": "", "info": "", "how": "", "candidates": [], "tried": []})
    write_config(port=None, serial=None)
    return jsonify(ok=True)


@app.get("/setup")
def setup_page():
    return render_template("setup.html")


@app.get("/api/setup")
def api_setup_get():
    cfg = load_config()
    return jsonify(**get_setup(), board={"port": cfg.get("port", ""), "serial": cfg.get("serial", "")})


@app.post("/api/level-limits")
def api_level_limits():
    """The popup next to the Level slider: the user's lowest and highest output level. Zero is never a limit: it means Off."""
    lo, hi, error = check_limits(request.get_json(silent=True) or {})
    if error:
        return jsonify(error=error), 400
    write_config(level_min=lo, level_max=hi)
    return jsonify(ok=True, level_min=lo, level_max=hi)


@app.post("/api/setup")
def api_setup_set():
    clean, error = check_setup(request.get_json(silent=True) or {})
    if error:
        return jsonify(error=error), 400
    write_config(**clean)
    return jsonify(ok=True, **clean)


_clock_cache = {}


@app.get("/api/clock-preview.png")
def api_clock_preview():
    """One frame of the SBB clock card with the saved callsign and locator, as it would be transmitted now."""
    import io
    import clock_card
    from flask import Response
    setup = get_setup()
    key = (setup["callsign"], setup["locator"])
    if _clock_cache.get("key") != key:
        _clock_cache.update(key=key, renderer=clock_card.ClockRenderer(*key))
    clock_card.CLOCK_AHEAD_SECONDS = setup["clock_ahead"]
    buf = io.BytesIO()
    _clock_cache["renderer"].frame(time.time()).save(buf, "PNG")
    return Response(buf.getvalue(), mimetype="image/png", headers={"Cache-Control": "no-store"})


def flash_worker(proc, port, serial_number):
    """Reads esptool's output into the flash log; on success waits for the new firmware and remembers the board."""
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        with lock:
            flash["log"].append(line)
            pct = flasher.percent(line)
            if pct is not None:
                flash["percent"] = pct
    rc = proc.wait()
    result, error = "", ""
    if rc == 0:
        time.sleep(3.0)                                   # the board boots the new firmware
        info = probe(port)
        if info:
            save_config(port, serial_number)
            with lock:
                conn.update({"tried": [], **found(port, serial_number, info, "flashed, saved")})
            result = f"flashed: {info}"
        else:
            result = "flashed, but the board does not answer yet: press Check"
    else:
        error = f"esptool failed (exit {rc}): see the log"
    with lock:
        flash.update(state="error" if error else "done", result=result, error=error, percent=100 if not error else flash["percent"])


@app.get("/api/flash/ports")
def api_flash_ports():
    """Espressif USB ports the user can pick (never flashed without a pick) and the state of the firmware bundle."""
    saved = load_config().get("serial")
    ok, text, _ = flasher.check_bundle()
    return jsonify(ports=[{"port": p, "serial": s, "saved": bool(saved) and s == saved} for p, s in sorted(espressif_ports().items())],
                   firmware={"ok": ok, "text": text})


@app.post("/api/flash/start")
def api_flash_start():
    d = request.get_json(silent=True) or {}
    port = d.get("port", "")
    ports = espressif_ports()
    if port not in ports:
        return jsonify(error="not an Espressif port"), 400
    ok, text, m = flasher.check_bundle()
    if not ok:
        return jsonify(error=text), 500
    with lock:
        if tx["proc"] is not None or tx["state"] in ("starting", "stopping"):
            return jsonify(error="stop the transmission first"), 409
        if flash["state"] == "flashing":
            return jsonify(error="already flashing"), 409
        flash.update(state="flashing", port=port, percent=0, error="", result="")
        flash["log"].clear()
    camera.stop_previews()
    try:
        proc = flasher.popen(port, m)
    except OSError as e:
        with lock:
            flash.update(state="error", error=str(e))
        return jsonify(error=str(e)), 500
    threading.Thread(target=flash_worker, args=(proc, port, ports[port]), daemon=True).start()
    return jsonify(ok=True)


@app.get("/api/flash/status")
def api_flash_status():
    with lock:
        return jsonify(state=flash["state"], port=flash["port"], percent=flash["percent"], error=flash["error"],
                       result=flash["result"], log=list(flash["log"])[-12:])


@app.get("/api/pictures")
def api_pictures():
    return jsonify(list_pictures())


@app.get("/api/cameras")
def api_cameras():
    """DirectShow cameras, each with its own microphone (or none: the stream then carries silence)."""
    return jsonify(camera.cameras())


@app.get("/api/audio")
def api_audio():
    """Audio inputs for the camera source, and the remembered choice ("auto" = the camera's own microphone) and delay."""
    cfg = load_config()
    return jsonify(devices=camera.audio_devices(), audio=cfg.get("audio", "auto"), delay=cfg.get("audio_delay", 0))


@app.post("/api/audio/detect")
def api_audio_detect():
    """Experimental clap test: start recording the camera and its microphone while the user claps; the page follows it with
    /api/audio/detect/status and /api/audio/detect/frame (clap_test.py, sound_sync.py from QOCAST). Nothing is saved."""
    d = request.get_json(silent=True) or {}
    chosen = next((c for c in camera.cameras() if c["name"] == d.get("camera")), None)
    if chosen is None:
        return jsonify(error="unknown camera: reload the camera list"), 400
    choice = d.get("audio", "auto")
    mic = chosen["mic"] if choice == "auto" else "" if choice == "none" else choice
    if not mic or (choice not in ("auto", "none") and choice not in camera.audio_devices()):
        return jsonify(error="choose a microphone first"), 400
    with lock:
        if tx["proc"] is not None or tx["state"] in ("starting", "stopping"):
            return jsonify(error="stop the transmission first"), 409
    camera.stop_previews()                      # a preview holds the camera
    time.sleep(0.5)
    if not clap_test.start(chosen["name"], mic):
        return jsonify(error="a measurement is already running"), 409
    return jsonify(ok=True, seconds=clap_test.SECONDS, mic=mic)


@app.get("/api/audio/detect/status")
def api_audio_detect_status():
    return jsonify(clap_test.snapshot())


@app.get("/api/audio/detect/frame")
def api_audio_detect_frame():
    data = clap_test.frame()
    return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "no-store"}) if data else ("", 204)


@app.get("/api/camera-preview")
def api_camera_preview():
    """Live MJPEG preview of a camera with the overlay. Not while transmitting: the transmission owns the camera then."""
    with lock:
        if tx["proc"] is not None or tx["state"] in ("starting", "stopping"):
            abort(409)
    name = request.args.get("camera", "")
    if name not in [c["name"] for c in camera.cameras()]:
        abort(404)
    return Response(stream_with_context(camera.preview_stream(name, get_setup()["callsign"])),
                    mimetype="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store"})


PLAYER_EXE = paths.PLAYER / "HB9IIU-Experimental-H266-Player.exe"
player = {"proc": None}


@app.get("/api/player")
def api_player():
    """Is the optional H.266 Player present (folder H266-Player next to C3CAST.exe)? The page shows its button only then."""
    return jsonify(available=PLAYER_EXE.is_file())


@app.post("/api/player/open")
def api_player_open():
    """Start the H.266 Player as its own program (it keeps running if C3CAST is closed). One window at a time."""
    if not PLAYER_EXE.is_file():
        return jsonify(error="the H.266 Player is not installed: the folder H266-Player is missing"), 404
    proc = player["proc"]
    if proc is not None and proc.poll() is None:
        return jsonify(ok=True, already=True)
    try:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        player["proc"] = subprocess.Popen([str(PLAYER_EXE)], cwd=str(PLAYER_EXE.parent), creationflags=flags, close_fds=True,
                                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return jsonify(error=f"could not start the player: {exc}"), 500
    return jsonify(ok=True)


@app.get("/api/bandplan")
def api_bandplan():
    """QO-100 slot rules (QOCAST's bandplan.py) for the spectrum, the downlink-to-uplink offset and the remembered frequency."""
    return jsonify(offset_mhz=bandplan.DOWNLINK_TO_UPLINK_OFFSET_KHZ / 1000,
                   allowed={str(sr): [k / 1000 for k in bandplan.allowed_slots(sr // 1000)] for sr in SYMBOL_RATES},
                   freq=get_freq(), min=FREQ_MIN, max=FREQ_MAX)


@app.get("/api/plan")
def api_plan():
    try:
        sr, fec, source = int(request.args.get("sr", 0)), request.args.get("fec", ""), request.args.get("source", "picture")
        if sr not in SYMBOL_RATES or fec not in FECS or source not in ("picture", "clock", "camera", "video"):
            raise ValueError
        return jsonify(qo100_enc.plan(sr // 1000, fec, source, request.args.get("codec", "h265")))
    except ValueError:
        abort(400)


@app.get("/api/status")
def api_status():
    with lock:
        running = tx["state"] == "transmitting"
        return jsonify(state=tx["state"], error=tx["error"], buffer=tx["buffer"], packets=tx["packets"],
                       elapsed=round(time.time() - tx["t0"]) if running else 0,
                       settings=tx["settings"], log=list(tx["log"])[-25:], flashing=flash["state"] == "flashing")


@app.post("/api/start")
def api_start():
    d = request.get_json(silent=True) or {}
    source = d.get("source", "picture")
    codec = d.get("codec", "h265")
    if codec not in ("h265", "h266"):
        return jsonify(error="unknown video codec"), 400
    if codec == "h266":
        try:
            qo100_enc.require_vvc()
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
    try:
        name, sr, fec, level = d.get("picture", ""), int(d["sr"]), d["fec"], int(d["level"])
    except (KeyError, TypeError, ValueError):
        return jsonify(error="bad request"), 400
    lo, hi = level_limits()
    if not lo <= level <= hi:
        return jsonify(error=f"output level must be {lo} to {hi} (your limits on the Setup page); zero disables transmission"), 400
    if source not in ("picture", "clock", "camera", "video"):
        return jsonify(error="unknown source"), 400
    if not setup_ready():
        return jsonify(error="set your callsign and locator on the Setup page first"), 400
    if source == "picture" and name not in list_pictures():
        return jsonify(error="unknown picture"), 400
    video_name = d.get("video", "")
    if source == "video" and video_name not in list_videos():
        return jsonify(error="unknown video: add a file to the videos folder and press Reload"), 400
    if source == "video":
        try:
            from stream_tx import video_has_audio
            video_has_audio(VIDEOS / video_name, codec)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
    camera_name = mic = ""
    delay = 0
    if source == "camera":
        chosen = next((c for c in camera.cameras() if c["name"] == d.get("camera")), None)
        if chosen is None:
            return jsonify(error="unknown camera: reload the camera list"), 400
        camera_name, mic = chosen["name"], chosen["mic"] or ""
        choice = d.get("audio", "auto")
        if choice == "none":
            mic = ""
        elif choice != "auto":
            if choice not in camera.audio_devices():
                return jsonify(error="unknown audio device: reload the list"), 400
            mic = choice
        try:
            delay = int(d.get("delay", 0))
        except (TypeError, ValueError):
            return jsonify(error="audio delay must be a number"), 400
        if not -500 <= delay <= 500:
            return jsonify(error="audio delay: -500 to 500 ms"), 400
        write_config(audio=choice, audio_delay=delay)
    camera.stop_previews()                  # a preview holds the camera; the transmission needs it
    if source == "camera":
        time.sleep(0.5)                     # let DirectShow release it
    if sr not in SYMBOL_RATES or fec not in FECS:
        return jsonify(error="value outside the allowed list"), 400
    freq, freq_error = check_freq(d.get("freq", get_freq()), sr)
    if freq_error:
        return jsonify(error=freq_error), 400
    with lock:
        if tx["proc"] is not None or tx["state"] in ("starting", "stopping"):
            return jsonify(error="already transmitting"), 409
        if flash["state"] == "flashing":
            return jsonify(error="the board is being flashed"), 409
        if not conn["connected"]:
            return jsonify(error="board not connected: run the connection check first"), 409
        port = conn["port"]
        tx.update(state="starting", error="", buffer="", packets="", stopping=False)
        tx["log"].clear()
        tx["settings"] = {"source": source, "picture": {"picture": name, "clock": "SBB clock", "camera": camera_name, "video": video_name}[source],
                          "sr": sr, "fec": fec, "level": level, "freq": freq, "codec": codec}
    try:
        setup = get_setup()
        cmd = [*paths.worker_cmd("stream_tx"), "--source", source, "--codec", codec,
               "--picture", str(PICTURES / name) if source == "picture" else "",
               "--video", str(VIDEOS / video_name) if source == "video" else "",
               "--camera", camera_name, "--mic", mic, "--delay", str(delay),
               "--port", port, "--freq", freq, "--baud", str(sr), "--fec", fec, "--amp", str(level),
               "--seconds", str(MAX_SECONDS), "--callsign", setup["callsign"], "--locator", setup["locator"],
               "--ahead", str(setup["clock_ahead"])]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", creationflags=flags)
    except Exception as e:
        with lock:
            tx.update(state="error", error=str(e))
        return jsonify(error=str(e)), 500
    write_config(freq=freq)                              # remembered for next time
    with lock:
        tx["proc"] = proc
    threading.Thread(target=reader, args=(proc,), daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/stop")
def api_stop():
    return jsonify(ok=stop_tx())


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "c3cast.ico")


@app.post("/api/quit")
def api_quit():
    """The END button: stop any transmission, then shut the server down (after this reply has been sent)."""
    stop_tx()
    if SERVER:
        threading.Timer(0.5, SERVER[0].shutdown).start()
    return jsonify(ok=True)


SERVER = []        # the running server, for /api/quit
WATCH = {"seen": time.time(), "bye": 0.0}
BYE_GRACE = 10          # s after the page said goodbye, with no page request since: quit
SILENT_LIMIT = 180      # s without any request: quit (hidden tabs are throttled to about one request a minute)
FIRST_PAGE_LIMIT = 120  # s to wait at startup for the first page


def watch_pages():
    """Quit (and stop any transmission) when no page is left: closed tab, crashed browser, sleeping PC. Never at startup before the
    first page has had time to open. C3CAST_NO_AUTOQUIT=1 turns it off."""
    started = time.time()
    first_seen = False
    while True:
        time.sleep(1)
        now = time.time()
        first_seen = first_seen or WATCH["seen"] > started + 0.5
        closed = WATCH["bye"] and now - WATCH["bye"] > BYE_GRACE and WATCH["seen"] < WATCH["bye"]
        silent = now - WATCH["seen"] > (SILENT_LIMIT if first_seen else FIRST_PAGE_LIMIT)
        if closed or silent:
            print(flush=True)
            print("  browser page closed: stopping" if closed else "  no browser page any more: stopping", flush=True)
            stop_tx()
            if SERVER:
                SERVER[0].shutdown()
            return


def free_port(first):
    """The first free local port from `first` on (a second C3CAST, or another program, may hold 5000)."""
    import socket
    for port in range(first, first + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"no free local port from {first} on")


WELCOME = """
  ============================================================
    {name} v{version}   -   the 5 EUR DATV modulator
    Plug. Flash. Play.                          by HB9IIU
  ============================================================

    Welcome, and thank you for trying C3CAST!

    Your browser opens at   {url}
    (if it does not, copy that address into your browser)

    Keep this window open while you use C3CAST;
    close it to quit.

    Licensed radio amateurs only. Use a filter before any
    amplifier. Firmware: ESP32-DATV by SP8ESA.

    73 de HB9IIU
  ============================================================
"""


def serve():
    """Run the web app. It opens the browser (C3CAST_NO_BROWSER=1 stops that; C3CAST_PORT sets the first port).
    The server is started directly (not through app.run), so Flask's and Werkzeug's development-server banner, with its red
    warning, and the line per request stay out of the console: only the welcome note and real errors show."""
    import logging
    from werkzeug.serving import make_server
    PICTURES.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=qo100_enc.video_encoder, daemon=True).start()     # GPU or software: decided once, silently
    port = free_port(int(os.environ.get("C3CAST_PORT", "5000")))
    url = f"http://127.0.0.1:{port}"
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    server = make_server("127.0.0.1", port, app, threaded=True)
    SERVER.append(server)
    if not os.environ.get("C3CAST_NO_AUTOQUIT"):
        threading.Thread(target=watch_pages, daemon=True).start()
    print(WELCOME.format(name=version.APP_NAME, version=version.__version__, url=url), flush=True)
    if not os.environ.get("C3CAST_NO_BROWSER"):
        import webbrowser
        threading.Timer(1.2, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_tx()
    print(flush=True)
    print("  73 de HB9IIU", flush=True)
    print(flush=True)


if __name__ == "__main__":
    serve()
