"""Live transmission of the SBB clock or a still picture, encoded the QOCAST way (qo100_enc.py) and sent to
host/tx_dvbs.py --ts -.

The transmitter is started first and is given null packets until its 'OK QPSKT' line appears; only then are ffmpeg
(and, for the clock, the frame writer) started, so the clock does not start late. SIGBREAK/SIGTERM/Ctrl-C stops it.
Its output lines (the transmitter's, plus 'ffmpeg: ...' lines) go to stdout for the web page.
"""
import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "host"))
sys.path.insert(0, str(HERE))
import clock_card  # noqa: E402
import qo100_enc  # noqa: E402
import version  # noqa: E402


def say(text):
    print(text, flush=True)


def source_settings(source, sr_ks, fec):
    """The clock uses QOCAST's tested tuning; pictures and the camera use the table defaults."""
    return qo100_enc.settings(sr_ks, fec, qo100_enc.clock_tuning(sr_ks, fec) if source == "clock" else None)


def build(source, picture, sr_ks, fec, callsign, locator, ahead, start_time, camera="", mic=""):
    """Return (settings, ffmpeg command) for the source. The clock takes raw frames on stdin; a picture or the
    camera is read by ffmpeg itself."""
    provider = f"{version.APP_NAME} @ {locator}"        # what receivers show as "Provider"
    if source == "camera":
        import camera as cam
        s = source_settings(source, sr_ks, fec)
        inputs, vf, audio_filter = cam.inputs_and_filter(camera, mic, s["size"], s["fps"], callsign)
        return s, qo100_enc.ffmpeg_command(s, inputs, callsign, provider, video_filter=vf, audio_filter=audio_filter)
    if source == "clock":
        s = source_settings(source, sr_ks, fec)
        clock_card.CLOCK_AHEAD_SECONDS = ahead
        inputs = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{clock_card.WIDTH}x{clock_card.HEIGHT}",
                  "-framerate", str(s["fps"]), "-i", "-",
                  "-re", "-f", "lavfi", "-i", f"aevalsrc='{clock_card.tone_expression(start_time)}':s=48000:c=mono"]
        return s, qo100_enc.ffmpeg_command(s, inputs, callsign, provider)
    s = source_settings(source, sr_ks, fec)
    w, h = s["size"].split("x")
    inputs = ["-re", "-loop", "1", "-framerate", str(s["fps"]), "-i", str(picture),
              "-re", "-f", "lavfi", "-i", f"aevalsrc='{qo100_enc.melody_expression()}':s=48000:c=mono"]
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    return s, qo100_enc.ffmpeg_command(s, inputs, callsign, provider, video_filter=vf)


def pump(stream, prefix, ready=None):
    for raw in iter(stream.readline, b""):
        line = raw.decode(errors="replace").rstrip()
        if not line:
            continue
        say(prefix + line)
        if ready is not None and line.startswith("OK QPSKT"):
            ready.set()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("clock", "picture", "camera"), required=True)
    ap.add_argument("--picture", default="")
    ap.add_argument("--camera", default="")
    ap.add_argument("--mic", default="")
    ap.add_argument("--port", required=True)
    ap.add_argument("--freq", required=True)
    ap.add_argument("--baud", type=int, required=True)
    ap.add_argument("--fec", required=True)
    ap.add_argument("--amp", type=int, required=True)
    ap.add_argument("--seconds", type=int, required=True)
    ap.add_argument("--callsign", required=True)
    ap.add_argument("--locator", required=True)
    ap.add_argument("--ahead", type=float, default=5.0)
    a = ap.parse_args(argv)
    sr_ks = a.baud // 1000

    stop = threading.Event()

    def on_signal(signum, frame):
        stop.set()

    for name in ("SIGBREAK", "SIGTERM", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)

    if not qo100_enc.FFMPEG.is_file():
        say(f"ERR ffmpeg not found: {qo100_enc.FFMPEG}")
        return 1
    if a.source == "picture" and not Path(a.picture).is_file():
        say(f"ERR picture not found: {a.picture}")
        return 1
    if a.source == "camera" and not a.camera:
        say("ERR no camera given")
        return 1
    s = source_settings(a.source, sr_ks, a.fec)
    runner = subprocess.Popen(
        [sys.executable, "-u", str(HERE / "runner.py"), "--port", a.port, "--freq", a.freq, "--baud", str(a.baud),
         "--dvbs2", "--mod", "qpsk", "--fec", a.fec, "--ts", "-", "--amp", str(a.amp), "--seconds", str(a.seconds),
         "--pa-enable"],                    # arms the PTT output (GPIO10 / D10): high while RF is on, low otherwise
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ready = threading.Event()
    threading.Thread(target=pump, args=(runner.stdout, "", ready), daemon=True).start()
    ffmpeg = None
    status = 0
    try:
        say(f"{a.source}: H.265 ({'GPU' if s['encoder'] == 'hevc_nvenc' else 'software'}) {s['size']} at {s['fps']} fps, video {s['video_bps'] // 1000} kb/s + audio {s['audio_k']} kb/s, "
            f"mux {s['muxrate'] // 1000} kb/s" + (f", {a.callsign} {a.locator}, lead {a.ahead:g} s" if a.source == "clock" else ""))
        deadline = time.time() + 40
        while not ready.is_set() and not stop.is_set() and runner.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        if not ready.is_set():
            if not stop.is_set():
                say("ERR transmitter did not start" if runner.poll() is None else f"ERR transmitter exited with code {runner.returncode}")
                status = 1
        else:
            start_time = time.time() + 0.5
            s, command = build(a.source, a.picture, sr_ks, a.fec, a.callsign, a.locator, a.ahead, start_time, a.camera, a.mic)
            ffmpeg = subprocess.Popen(command, stdin=subprocess.PIPE if a.source == "clock" else subprocess.DEVNULL,
                                      stdout=runner.stdin, stderr=subprocess.PIPE)
            runner.stdin.close()        # ffmpeg holds the pipe now; the transmitter sees EOF if ffmpeg dies
            threading.Thread(target=pump, args=(ffmpeg.stderr, "ffmpeg: "), daemon=True).start()
            if a.source == "clock":
                feed = clock_card.frame_feeder(clock_card.ClockRenderer(a.callsign, a.locator), start_time, s["fps"])
                threading.Thread(target=feed, args=(ffmpeg.stdin, stop), daemon=True).start()
            while not stop.is_set() and runner.poll() is None and ffmpeg.poll() is None:
                time.sleep(0.1)
            if ffmpeg.poll() is not None and not stop.is_set() and runner.poll() is None:
                say(f"ERR ffmpeg stopped (exit {ffmpeg.returncode})")
                status = 1
    finally:
        stop.set()
        if runner.poll() is None and os.name != "nt":
            runner.send_signal(signal.SIGINT)   # on Windows the CTRL_BREAK reached the whole process group
        if ffmpeg is not None and ffmpeg.poll() is None:
            if ffmpeg.stdin:
                try:
                    ffmpeg.stdin.close()
                except OSError:
                    pass
            ffmpeg.terminate()
        try:
            runner.wait(timeout=12)
        except subprocess.TimeoutExpired:
            runner.kill()
    return status


if __name__ == "__main__":
    sys.exit(main())
