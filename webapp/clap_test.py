"""The clap test with a live picture and a microphone level: one ffmpeg process records the camera and its microphone (as one
DirectShow input, like on air) to a file for sound_sync.py, and at the same time gives the page a small live picture (MJPEG on
stdout) and the microphone level (from the raw audio it also writes to a file). Experimental."""
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

import sound_sync

SECONDS = sound_sync.RECORD_SECONDS

state = {"state": "idle", "started": 0.0, "error": "", "result": None, "frame": b"", "level": 0.0, "mic": ""}
_lock = threading.Lock()


def busy():
    return state["state"] in ("starting", "recording", "analysing")


def snapshot():
    """Status for the page: the state, seconds left, the microphone level 0..1 (-60 to 0 dB) and the result."""
    with _lock:
        left = max(0, round(SECONDS - (time.time() - state["started"]))) if state["state"] == "recording" else 0
        return {"state": state["state"], "left": left, "level": state["level"], "error": state["error"],
                "result": state["result"], "mic": state["mic"]}


def frame():
    return state["frame"]


def _command(transmit, folder):
    """The transmission's own ffmpeg command (as QOCAST does), writing the stream to a file for SECONDS instead of
    to the transmitter. The page's live picture and microphone level come from extra outputs of the same process,
    so the camera is opened once, exactly as on air. Options before an output belong to that output (-t each)."""
    command = list(transmit)
    if command[-1] != "-":
        raise ValueError("unexpected transmit command")
    t = ["-t", str(SECONDS)]
    return [*command[:-1], *t, str(Path(folder) / "claps.ts"),
            *t, "-map", "0:v", "-vf", "fps=12,scale=480:-2", "-q:v", "6", "-f", "mjpeg", "pipe:1",
            *t, "-map", "0:a", "-ac", "2", "-ar", "48000", "-flush_packets", "1", "-f", "s16le", str(Path(folder) / "levels.raw")]


def _pump_frames(stream):
    """Keep the latest complete JPEG (FFD8 ... FFD9) from ffmpeg's stdout."""
    buf = b""
    while True:
        chunk = stream.read(4096)
        if not chunk:
            return
        buf += chunk
        while True:
            start = buf.find(b"\xff\xd8")
            end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
            if start < 0:
                buf = buf[-1:]
                break
            if end < 0:
                buf = buf[start:]
                break
            state["frame"] = buf[start:end + 2]
            buf = buf[end + 2:]


def _watch_level(path, proc):
    """Microphone level from the raw audio ffmpeg writes (48 kHz stereo 16 bit, flushed about every 0.2 s)."""
    block = 4800 * 4                                    # 100 ms
    done = 0
    while proc.poll() is None:
        time.sleep(0.1)
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        data = data[done:len(data) - (len(data) - done) % 4]
        if not data:
            continue
        done += len(data)
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
        rms = max(float(np.sqrt(np.mean(samples[k:k + block // 2] ** 2))) for k in range(0, len(samples), block // 2))
        db = 20 * np.log10(max(rms, 1.0) / 32768)
        state["level"] = float(min(1.0, max(0.0, (db + 60.0) / 60.0)))


def _run(transmit):
    try:
        with tempfile.TemporaryDirectory(prefix="c3cast_clap_") as tmp:
            proc = subprocess.Popen(_command(transmit, tmp), cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            threading.Thread(target=_pump_frames, args=(proc.stdout,), daemon=True).start()
            errors = []
            threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True).start()
            threading.Thread(target=_watch_level, args=(Path(tmp) / "levels.raw", proc), daemon=True).start()
            began = time.time()
            while proc.poll() is None and time.time() - began < SECONDS + 20:
                if state["frame"] and state["state"] == "starting":
                    with _lock:
                        state.update(state="recording", started=time.time())
                time.sleep(0.1)
            if proc.poll() is None:
                proc.kill()
                raise RuntimeError("the camera or microphone did not answer: close other programs using them")
            time.sleep(0.3)
            path = Path(tmp) / "claps.ts"
            if proc.returncode or not path.is_file():
                tail = (errors[0].decode(errors="replace").strip()[-160:] if errors else "")
                raise RuntimeError("could not record from the camera and microphone (in use elsewhere?) " + tail)
            with _lock:
                state["state"] = "analysing"
            kept = Path(tempfile.gettempdir()) / "c3cast_last_sound_sync.ts"      # kept for support: the last recording, to look at it
            shutil.copyfile(path, kept)
            result = sound_sync.measure(path, transmitted=True)
            print(f"Sound sync: {result} (recording kept: {kept})", flush=True)
        with _lock:
            state.update(state="done", result={"delay": -result["offset_ms"], "score": result["score"], "clear": result["clear"]})
    except (RuntimeError, ValueError, OSError) as e:
        with _lock:
            state.update(state="error", error=str(e))
    finally:
        state["frame"] = b""
        state["level"] = 0.0


def start(transmit, mic):
    """Start the test in the background; False if one is already running."""
    with _lock:
        if busy():
            return False
        state.update(state="starting", started=time.time(), error="", result=None, frame=b"", level=0.0, mic=mic)
    threading.Thread(target=_run, args=(transmit,), daemon=True).start()
    return True
