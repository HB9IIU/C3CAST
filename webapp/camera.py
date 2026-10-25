"""USB camera source: DirectShow discovery, capture options, microphone pairing and the picture overlay.
Ported from HB9IIU/QOCAST (devices.py, overlays.py, engine.build_camera_ffmpeg_command), reduced to what this project uses.

Overlay (drawn by ffmpeg at the transmitted size, on semi-transparent dark bands): the callsign top left, the UTC time
HH:MM:SS top right, a scrolling marquee along the bottom. The texts go through small files (textfile=), so any
characters are safe.
"""
import re
import subprocess
import threading
from pathlib import Path

import qo100_enc
import version

HERE = Path(__file__).resolve().parent
FOLDER = HERE / "overlays"
MARQUEE_TEXT = f"TRANSMITTED WITH {version.APP_NAME} v{version.__version__} · FIRMWARE BY SP8ESA"
TIME_TEXT = "%{gmtime:%H\\:%M\\:%S} UTC"       # ffmpeg text expansion; the file holds %{gmtime:%H\:%M\:%S} UTC
FONT = "C:/Windows/Fonts/arialbd.ttf"           # banner: bold
MARQUEE_FONT = "C:/Windows/Fonts/arial.ttf"     # marquee: regular, calmer to read
BAND = 0.055                                    # band height, part of the picture height
MARQUEE_SPEED = 90 / 720                        # picture heights per second (90 px/s at 720p)
MARQUEE_GAP = "        ·        "
SHADE = "black@0.65"

# Live microphones are often too loud and clip. A compressor (4:1 above -20 dBFS, no look-ahead) brings speech to about
# broadcast loudness; the limiter keeps peaks at 70 % of full scale. Works for any mic (QOCAST's MICROPHONE_FILTER).
MICROPHONE_FILTER = ("acompressor=threshold=0.1:ratio=4:attack=5:release=250:makeup=1,"
                     "alimiter=limit=0.7:level=0,lowpass=20000")

_DEVICE = re.compile(r'\] "(?P<name>[^"]+)" \((?P<kind>video|audio)\)')
# "vcodec=mjpeg  min s=1280x720 fps=5 max s=1280x720 fps=30" or "pixel_format=yuyv422 ..."
_FORMAT = re.compile(r"(?P<key>vcodec|pixel_format)=(?P<value>\S+)\s+min s=\S+ fps=\S+ "
                     r"max s=(?P<size>\d+x\d+) fps=(?P<fps>[\d.]+)")
_GENERIC = {"video", "camera", "audio", "microphone", "webcam", "usb", "input", "mic", "virtual"}


def _run(args):
    return subprocess.run(
        [str(qo100_enc.FFMPEG), "-hide_banner", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",     # ffmpeg writes UTF-8 names
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stderr


_ANY_DEVICE = re.compile(r'\] "(?P<name>[^"]+)" \((?P<kind>[^)]+)\)')
_ALT_NAME = re.compile(r'Alternative name "(?P<alt>[^"]+)"')


def _enumerate():
    """[{"name", "kind", "alt"}] for every DirectShow device, in ffmpeg's order. "alt" is the Windows device path: a
    physical USB device has "usb#vid_..." in it; virtual cameras (DroidCam, Camo, OBS, NVIDIA Broadcast) do not."""
    found, last = [], None
    for line in _run(["-list_devices", "true", "-f", "dshow", "-i", "dummy"]).splitlines():
        header = _ANY_DEVICE.search(line)
        if header:
            last = {"name": header["name"], "kind": header["kind"], "alt": ""} if header["kind"] in ("video", "audio") else None
            if last:
                found.append(last)
            continue
        alt = _ALT_NAME.search(line)
        if alt and last and not last["alt"]:
            last["alt"] = alt["alt"]
    return found


def list_devices():
    """{"video": [...], "audio": [...]} DirectShow device names."""
    devices = {"video": [], "audio": []}
    for d in _enumerate():
        devices[d["kind"]].append(d["name"])
    return devices


def _tokens(name):
    return set(re.findall(r"[a-z0-9]+", name.lower())) - _GENERIC


def pair_microphone(camera, microphones):
    """The camera's own microphone: the audio device sharing the most name words with it (e.g. "Camo" and
    "Microphone (Camo)"), or None when there is no such device (then the stream carries silence)."""
    for m in microphones:                                     # "USB Camera" in "Microphone (USB Camera)"
        if camera.lower() in m.lower():
            return m
    best = max(microphones, key=lambda m: len(_tokens(camera) & _tokens(m)), default=None)
    return best if best and _tokens(camera) & _tokens(best) else None


def cameras():
    """[{"name": camera, "mic": its microphone or None, "usb": physical USB camera}] for every DirectShow camera,
    physical USB cameras first (then the virtual ones), each group in ffmpeg's order."""
    devices = _enumerate()
    mics = [d["name"] for d in devices if d["kind"] == "audio"]
    cams = [{"name": d["name"], "mic": pair_microphone(d["name"], mics), "usb": "usb#vid_" in d["alt"].lower()}
            for d in devices if d["kind"] == "video"]
    return sorted(cams, key=lambda c: not c["usb"])        # stable: USB first


_formats = {}


def camera_formats(camera):
    """What the camera offers: [(kind, value, "WxH", max fps)]. It cannot be asked while the camera is in use, so an
    empty answer is not kept; a real answer is, so the preview and the transmission do not ask twice."""
    if camera not in _formats:
        found = [(m["key"], m["value"], m["size"], float(m["fps"]))
                 for m in _FORMAT.finditer(_run(["-list_options", "true", "-f", "dshow", "-i", f"video={camera}"]))]
        if not found:
            return []
        _formats[camera] = found
    return _formats[camera]


def capture_options(camera, size, fps=30, formats=None):
    """DirectShow input options for ``camera`` at ``size``: MJPEG when the camera has it (many webcams give only 5-10 fps
    uncompressed at 720p), otherwise its fastest uncompressed format. Without a match: let the camera choose."""
    formats = camera_formats(camera) if formats is None else formats
    at_size = [f for f in formats if f[2] == size]
    mjpeg = [f for f in at_size if f[0] == "vcodec" and f[1] == "mjpeg"]
    if mjpeg or not formats:
        return ["-vcodec", "mjpeg", "-video_size", size, "-framerate", str(fps)]
    raw = sorted((f for f in at_size if f[0] == "pixel_format"), key=lambda f: -f[3])
    if raw:
        return ["-pixel_format", raw[0][1], "-video_size", size, "-framerate", f"{min(fps, raw[0][3]):g}"]
    return []


def _path(name):
    """A filter-safe path: forward slashes, the drive colon escaped."""
    return str(FOLDER / name).replace("\\", "/").replace(":", "\\:")


def _write(name, text):
    FOLDER.mkdir(parents=True, exist_ok=True)
    (FOLDER / name).write_text(text, encoding="utf-8")
    return _path(name)


def overlay_filter(callsign):
    """The drawbox/drawtext chain. Sizes are expressions of the picture height, so it fits every picture size."""
    band = f"(ih*{BAND})"                    # drawbox: ih; drawtext: h
    text_band = f"(h*{BAND})"
    margin = f"(h*{BAND * 0.4})"

    def style(fontfile):
        return (f"fontfile='{fontfile.replace(':', chr(92) + ':')}'"
                f":fontsize=h*{BAND * 0.62:.4f}:fontcolor=white")

    middle = f"({text_band}-th)/2"           # text centred in a band
    unit = MARQUEE_TEXT + MARQUEE_GAP
    return ",".join([
        f"drawbox=x=0:y=0:w=iw:h={band}:color={SHADE}:t=fill",
        f"drawtext={style(FONT)}:textfile='{_write('banner_left.txt', callsign)}':expansion=none:x={margin}:y={middle}",
        f"drawtext={style(FONT)}:textfile='{_write('banner_right.txt', TIME_TEXT)}'"
        f":expansion=normal:x=w-tw-{margin}:y={middle}",
        f"drawbox=x=0:y=ih-{band}:w=iw:h={band}:color={SHADE}:t=fill",
        # Starts at the right edge, scrolls left, comes back after one full pass.
        f"drawtext={style(MARQUEE_FONT)}:textfile='{_write('marquee.txt', unit)}'"
        f":expansion=none:x=w-mod(t*h*{MARQUEE_SPEED:.4f}\\,w+tw):y=h-{text_band}+{middle}",
    ])


_previews = []
_preview_lock = threading.Lock()


def stop_previews():
    """Stop every running preview (the camera is free again). Called before a transmission and when a new preview starts."""
    with _preview_lock:
        procs = list(_previews)
        _previews.clear()
    for p in procs:
        if p.poll() is None:
            p.kill()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def preview_stream(camera, callsign):
    """Generator of multipart/x-mixed-replace JPEG parts: 640x360 at 10 fps, with the overlay as it will be transmitted.
    One preview at a time; it ends when the client goes away, or when stop_previews() is called."""
    stop_previews()
    vf = f"fps=10,scale=640:360,setsar=1,{overlay_filter(callsign)}"
    cmd = [str(qo100_enc.FFMPEG), "-nostdin", "-hide_banner", "-loglevel", "error",
           "-f", "dshow", "-rtbufsize", "50M", *capture_options(camera, "1280x720"), "-i", f"video={camera}",
           "-an", "-vf", vf, "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "7", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with _preview_lock:
        _previews.append(proc)
    buf = b""
    try:
        while True:
            chunk = proc.stdout.read1(65536)
            if not chunk:
                break
            buf += chunk
            while True:                                     # a JPEG runs from FFD8 to FFD9 (FF is always stuffed inside)
                start = buf.find(b"\xff\xd8")
                end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                if start < 0 or end < 0:
                    break
                frame, buf = buf[start:end + 2], buf[end + 2:]
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame)) + frame + b"\r\n"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        with _preview_lock:
            if proc in _previews:
                _previews.remove(proc)


def inputs_and_filter(camera, mic, size, fps, callsign):
    """(ffmpeg inputs, -vf chain, audio filter) for a camera at the transmitted picture ``size``."""
    width, height = size.split("x")
    capture_size = "1280x720" if int(width) <= 1280 else "1920x1080"
    device = f"video={camera}" + (f":audio={mic}" if mic else "")
    inputs = ["-f", "dshow", "-rtbufsize", "100M", "-audio_buffer_size", "50",
              *capture_options(camera, capture_size, fps), "-i", device]
    if not mic:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]      # no microphone: silence
    vf = f"fps={fps},scale={width}:{height},setsar=1,{overlay_filter(callsign)}"
    return inputs, vf, (MICROPHONE_FILTER if mic else "lowpass=20000")
