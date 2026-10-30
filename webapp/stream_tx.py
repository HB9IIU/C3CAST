"""Live transmission of the SBB clock or a still picture, encoded the QOCAST way (qo100_enc.py) and sent to
host/tx_dvbs.py --ts -.

The transmitter is started first and is given null packets until its 'OK QPSKT' line appears; only then are ffmpeg
(and, for the clock, the frame writer) started, so the clock does not start late. SIGBREAK/SIGTERM/Ctrl-C stops it.
Its output lines (the transmitter's, plus 'ffmpeg: ...' lines) go to stdout for the web page.
"""
import argparse
import os
import re
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
import paths  # noqa: E402
import qo100_enc  # noqa: E402
import version  # noqa: E402


def say(text):
    print(text, flush=True)


def source_settings(source, sr_ks, fec, codec="h265"):
    """The clock uses QOCAST's tested tuning; pictures and the camera use the table defaults."""
    return qo100_enc.source_settings(source, sr_ks, fec, codec)


def video_has_audio(path, codec="h265"):
    """Validate a local media file before RF; allow video-only files with silent AAC. ffmpeg itself reads the stream list,
    so the packaged app does not need ffprobe. Headers only: no output file, so nothing is decoded and a long film takes no time
    (ffmpeg then ends with exit code 1, "at least one output file must be specified", which is expected)."""
    try:
        result = subprocess.run([str(qo100_enc.ffmpeg_path(codec)), "-hide_banner", "-i", str(path)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"Cannot read the selected video: {exc}") from exc
    streams = re.findall(r"Stream #\d+:\d+.*?: (Video|Audio): (.*)", result.stderr)      # one line per stream
    has_video = any(kind == "Video" and "attached pic" not in rest for kind, rest in streams)
    if not has_video:
        raise ValueError("The selected file has no readable video stream")
    return any(kind == "Audio" for kind, _ in streams)


def video_info(path, codec="h265"):
    """What ffmpeg finds in a local video, as plain text for the page: {"summary", "heavy", "notes"}. Only reads the stream list
    (like video_has_audio), so the packaged app needs nothing more than ffmpeg. "heavy" is a warning when the file is large enough that
    decoding it live may stutter; "notes" are things the user should know (black bars, silence). Headers only, like video_has_audio."""
    try:
        result = subprocess.run([str(qo100_enc.ffmpeg_path(codec)), "-hide_banner", "-i", str(path)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"Cannot read the selected video: {exc}") from exc
    text = result.stderr
    video = next((m for m in re.finditer(r"Stream #\d+:\d+.*?: Video: (.*)", text) if "attached pic" not in m[1]), None)
    if video is None:
        raise ValueError("The selected file has no readable video stream")
    line = video[1]
    name = re.match(r"\w+", line)[0]
    size = re.search(r", (\d{2,5})x(\d{2,5})[ ,\[]", line + " ")
    rate = re.search(r"([\d.]+) fps", line) or re.search(r"([\d.]+) tbr", line)
    width, height = (int(size[1]), int(size[2])) if size else (0, 0)
    fps = float(rate[1]) if rate else 0.0
    has_audio = re.search(r"Stream #\d+:\d+.*?: Audio:", text) is not None
    length = re.search(r"Duration: (\d+):(\d+):(\d+)", text)
    seconds = int(length[1]) * 3600 + int(length[2]) * 60 + int(length[3]) if length else 0
    names = {"h264": "H.264", "hevc": "H.265", "vvc": "H.266", "av1": "AV1", "vp9": "VP9", "mpeg4": "MPEG-4", "mpeg2video": "MPEG-2", "vp8": "VP8"}
    parts = [f"{width}\u00d7{height}" if width else "size unknown", f"{fps:g} fps" if fps else "frame rate unknown", names.get(name, name)]
    if seconds:
        parts.append(f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02d}")
    parts.append("with sound" if has_audio else "no sound")
    heavy, notes = "", []
    big = []
    if width * height > 2100000:                                  # more pixels than 1920x1080, whichever way up
        big.append("bigger than 1080p")
    if fps > 30.5:
        big.append(f"{fps:g} fps")
    if name in ("av1",):
        big.append("AV1 is slow to decode")
    if big:
        heavy = ("Heavy file (" + ", ".join(big) + "): your PC may stutter decoding it live. Nothing above 1080p and 30 fps is ever sent, "
                 "so prepare the file first: press the i button.")
    if width and height and abs(width / height - 16 / 9) > 0.03:
        notes.append("Not 16:9: black bars will be added.")
    if not has_audio:
        notes.append("No sound in the file: silence will be sent.")
    return {"summary": " \u00b7 ".join(parts), "heavy": heavy, "notes": notes}


def build(source, picture, sr_ks, fec, callsign, locator, ahead, start_time, camera="", mic="", delay_ms=0, codec="h265", video=""):
    """Return (settings, ffmpeg command) for the source. The clock takes raw frames on stdin; a picture or the
    camera is read by ffmpeg itself."""
    provider = f"{version.APP_NAME} @ {locator}"        # what receivers show as "Provider"
    if source == "video":
        has_audio = video_has_audio(video, codec)
        s = source_settings(source, sr_ks, fec, codec)
        inputs = ["-re", "-stream_loop", "-1", "-i", str(video)]
        if not has_audio:
            inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
        inputs += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0"]
        w, h = s["size"].split("x")
        vf = f"fps={s['fps']},setpts=N/({s['fps']}*TB),scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        inputs += ["-fps_mode", "cfr"]
        return s, qo100_enc.ffmpeg_command(s, inputs, callsign, provider, video_filter=vf,
                                          audio_filter="asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0,lowpass=20000")
    if source == "camera":
        import camera as cam
        s = source_settings(source, sr_ks, fec, codec)
        inputs, vf, audio_filter = cam.inputs_and_filter(camera, mic, s["size"], s["fps"], callsign, delay_ms)
        return s, qo100_enc.ffmpeg_command(s, inputs, callsign, provider, video_filter=vf, audio_filter=audio_filter)
    if source == "clock":
        s = source_settings(source, sr_ks, fec, codec)
        clock_card.CLOCK_AHEAD_SECONDS = ahead
        inputs = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{clock_card.WIDTH}x{clock_card.HEIGHT}",
                  "-framerate", str(s["fps"]), "-i", "-",
                  "-re", "-f", "lavfi", "-i", f"aevalsrc='{clock_card.tone_expression(start_time)}':s=48000:c=mono"]
        return s, qo100_enc.ffmpeg_command(s, inputs, callsign, provider)
    s = source_settings(source, sr_ks, fec, codec)
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
    ap.add_argument("--codec", choices=("h265", "h266"), default="h265")
    ap.add_argument("--source", choices=("clock", "picture", "camera", "video"), required=True)
    ap.add_argument("--video", default="")
    ap.add_argument("--picture", default="")
    ap.add_argument("--camera", default="")
    ap.add_argument("--mic", default="")
    ap.add_argument("--delay", type=int, default=0, help="camera: audio delay in ms (negative: picture delay)")
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
    if not 1 <= a.amp <= 480:
        ap.error("output level must be 1 to 480; zero disables transmission")
    sr_ks = a.baud // 1000

    stop = threading.Event()

    def on_signal(signum, frame):
        stop.set()

    for name in ("SIGBREAK", "SIGTERM", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)

    if not qo100_enc.ffmpeg_path(a.codec).is_file():
        say(f"ERR ffmpeg not found: {qo100_enc.ffmpeg_path(a.codec)}")
        return 1
    if a.codec == "h266":
        try:
            qo100_enc.require_vvc()
        except ValueError as exc:
            say(f"ERR {exc}")
            return 1
    if a.source == "picture" and not Path(a.picture).is_file():
        say(f"ERR picture not found: {a.picture}")
        return 1
    if a.source == "camera" and not a.camera:
        say("ERR no camera given")
        return 1
    if a.source == "video":
        try:
            video_has_audio(a.video, a.codec)
        except ValueError as exc:
            say(f"ERR {exc}")
            return 1
    s = source_settings(a.source, sr_ks, a.fec, a.codec)
    runner = subprocess.Popen(
        [*paths.worker_cmd("runner"), "--port", a.port, "--freq", a.freq, "--baud", str(a.baud),
         "--dvbs2", "--mod", "qpsk", "--fec", a.fec, "--ts", "-", "--amp", str(a.amp), "--seconds", str(a.seconds),
         "--pa-enable"],                    # arms the PTT output (GPIO10 / D10): high while RF is on, low otherwise
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ready = threading.Event()
    threading.Thread(target=pump, args=(runner.stdout, "", ready), daemon=True).start()
    ffmpeg = None
    status = 0
    try:
        say(f"{a.source}: {'H.266 experimental' if a.codec == 'h266' else 'H.265'} ({'GPU' if s['encoder'] == 'hevc_nvenc' else 'software'}) {s['size']} at {s['fps']} fps, video {s['video_bps'] // 1000} kb/s + audio {s['audio_k']} kb/s, "
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
            s, command = build(a.source, a.picture, sr_ks, a.fec, a.callsign, a.locator, a.ahead, start_time, a.camera, a.mic, a.delay, a.codec, a.video)
            if a.codec == "h266":
                say("H.266: encoder warming up; the transmitter sends null packets until video arrives. Real-time performance is experimental.")
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
