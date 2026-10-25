"""Encoder strategy copied from HB9IIU/QOCAST (qo100_table.py, engine.build_ffmpeg_command, engine.melody_expression).

DATV-Easy V3.08 "All Automatic" picture sizes and audio rates, H.265 on NVENC (CBR, p7, low latency), AAC-HE v2 audio,
video bitrate = (mux - audio - 51520) / 1.12. The clock additionally uses QOCAST's tested per-profile tuning
(testcards/sbb_clock.qoweb.json: size, fps, video-rate stretch).

Differences from QOCAST, because the sink is the ESP32 and not a Pluto:
- the multiplex rate is 96.5 % of this channel's capacity (upstream tx_media.py margin; QOCAST sends the exact capacity),
  and the capacity is the one of tx_dvbs.py (normal frames, no pilots);
- the transport stream goes to stdout (for tx_dvbs.py --ts -) instead of UDP to the Pluto.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "host"))
import dvbs2  # noqa: E402

FFMPEG = HERE.parent / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"     # QOCAST's build: hevc_nvenc + libfdk_aac
MUX_MARGIN = 0.965
SDT_PERIOD_S = 0.5
CLOCK_TUNING_FILE = HERE / "testcards" / "sbb_clock.qoweb.json"

# (SR kS/s, FEC) -> picture size and audio. 125 kS/s is QOCAST's own choice (very little video).
_S = dict
QO100 = {
    (125, "1/2"): _S(size="640x360", audio_k=16, aac_he_v2=True, pcr_ms=30, pat_s=0.45),
    (125, "2/3"): _S(size="640x360", audio_k=16, aac_he_v2=True, pcr_ms=30, pat_s=0.45),
    (125, "3/4"): _S(size="640x360", audio_k=16, aac_he_v2=True, pcr_ms=30, pat_s=0.45),
    (125, "4/5"): _S(size="640x360", audio_k=16, aac_he_v2=True, pcr_ms=30, pat_s=0.45),
    (250, "1/2"): _S(size="854x480", audio_k=16, aac_he_v2=True, pcr_ms=30, pat_s=0.45),
    (250, "2/3"): _S(size="960x540", audio_k=24, aac_he_v2=True, pcr_ms=30, pat_s=0.4),
    (250, "3/4"): _S(size="960x540", audio_k=24, aac_he_v2=True, pcr_ms=30, pat_s=0.4),
    (250, "4/5"): _S(size="960x540", audio_k=24, aac_he_v2=True, pcr_ms=30, pat_s=0.4),
    (333, "1/2"): _S(size="960x540", audio_k=24, aac_he_v2=True, pcr_ms=30, pat_s=0.4),
    (333, "2/3"): _S(size="1280x720", audio_k=32, aac_he_v2=True, pcr_ms=20, pat_s=0.4),
    (333, "3/4"): _S(size="1280x720", audio_k=32, aac_he_v2=True, pcr_ms=20, pat_s=0.4),
    (333, "4/5"): _S(size="1280x720", audio_k=32, aac_he_v2=True, pcr_ms=20, pat_s=0.4),
    (500, "1/2"): _S(size="1280x720", audio_k=32, aac_he_v2=True, pcr_ms=20, pat_s=0.4),
    (500, "2/3"): _S(size="1600x900", audio_k=48, aac_he_v2=True, pcr_ms=20, pat_s=0.2),
    (500, "3/4"): _S(size="1600x900", audio_k=48, aac_he_v2=True, pcr_ms=20, pat_s=0.2),
    (500, "4/5"): _S(size="1600x900", audio_k=48, aac_he_v2=True, pcr_ms=20, pat_s=0.2),
    (1000, "1/2"): _S(size="1920x1080", audio_k=96, aac_he_v2=True, pcr_ms=20, pat_s=0.1),
    (1000, "2/3"): _S(size="1920x1080", audio_k=96, aac_he_v2=True, pcr_ms=20, pat_s=0.1),
    (1000, "3/4"): _S(size="1920x1080", audio_k=96, aac_he_v2=True, pcr_ms=20, pat_s=0.1),
    (1000, "4/5"): _S(size="1920x1080", audio_k=128, aac_he_v2=False, pcr_ms=20, pat_s=0.1),
}

# Notes of the testcard melody: (Hz, seconds). Volume steps up on each repeat so levels can be checked.
TESTCARD_MELODY = [(294, 0.20), (392, 0.40), (392, 0.20), (392, 0.20), (370, 0.20),
                   (330, 0.20), (294, 0.40), (262, 0.20), (247, 0.40), (294, 0.20)]
TESTCARD_MELODY_REST_S = 1.5
TESTCARD_MELODY_VOLUMES = [0.05, 0.25, 0.50, 0.75, 1.00]
_NOTE_FADE_S = 0.01


def melody_expression():
    """ffmpeg aevalsrc expression playing the testcard melody forever (generated live, never looped from a file)."""
    repeat_s = sum(d for _, d in TESTCARD_MELODY) + TESTCARD_MELODY_REST_S
    cycle_s = repeat_s * len(TESTCARD_MELODY_VOLUMES)
    u = f"mod(t,{repeat_s:g})"
    notes, start = [], 0.0
    for freq, duration in TESTCARD_MELODY:
        end = start + duration
        envelope = f"min(1,min(({u}-{start:g})/{_NOTE_FADE_S},({end:g}-{u})/{_NOTE_FADE_S}))"
        notes.append(f"gte({u},{start:g})*lt({u},{end:g})*{envelope}*sin(2*PI*{freq}*t)")
        start = end
    repeat = f"floor(mod(t,{cycle_s:g})/{repeat_s:g})"
    volume = "+".join(f"{v:g}*eq({repeat},{i})" for i, v in enumerate(TESTCARD_MELODY_VOLUMES))
    return f"({volume})*({'+'.join(notes)})"


_encoder = None


def video_encoder():
    """"hevc_nvenc" when this PC has a working NVIDIA encoder, otherwise "libx265" (software). Decided once, silently, by
    a 0.2 s trial encode (a GPU-less PC lists hevc_nvenc too, but cannot use it). C3CAST_ENCODER=nvenc|software overrides."""
    global _encoder
    forced = os.environ.get("C3CAST_ENCODER", "").strip().lower()
    if forced in ("nvenc", "software"):
        return "hevc_nvenc" if forced == "nvenc" else "libx265"
    if _encoder is None:
        try:
            r = subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                "color=black:s=256x256:r=30:d=0.2", "-c:v", "hevc_nvenc", "-f", "null", "-"],
                               capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _encoder = "hevc_nvenc" if r.returncode == 0 else "libx265"
        except (OSError, subprocess.SubprocessError):
            _encoder = "libx265"
    return _encoder


def x265_preset(size):
    """Software encoding must keep up in real time on an ordinary PC: faster presets for bigger pictures."""
    width = int(size.split("x")[0])
    return "ultrafast" if width >= 1600 else "superfast" if width >= 1280 else "veryfast"


def clock_tuning(sr_ks, fec):
    """QOCAST's tested size/fps/rate for the SBB clock at this SR/FEC, or {} (125 kS/s was never tuned)."""
    try:
        entry = json.loads(CLOCK_TUNING_FILE.read_text())["profiles"].get(f"SR {sr_ks} / FEC {fec}")
    except (OSError, ValueError, KeyError):
        return {}
    return entry["tuning"] if entry and entry.get("passed") else {}


def settings(sr_ks, fec, tuning=None):
    """Everything the ffmpeg command needs for one SR/FEC (tuning: size, fps, rate, multipass; may be empty)."""
    tuning = tuning or {}
    t = QO100[(sr_ks, fec)]
    cap = dvbs2.ts_rate(sr_ks * 1000, fec, "normal", False, "qpsk")
    mux = int(cap * MUX_MARGIN)
    video = (mux - t["audio_k"] * 1000 - 51520) / 1.12            # DATV-Easy V3.08 formulas
    bufsize = video / 4 + 180000
    encoder = video_encoder()
    # QOCAST's video-rate stretch (up to 1.3) was tuned on NVENC, which undershoots on the static clock card. x265 follows
    # its target, so with the stretch video + audio could exceed the multiplex: software encoding uses the plain budget.
    rate = tuning.get("rate", 1.0) if encoder == "hevc_nvenc" else 1.0
    return {"encoder": encoder, "size": tuning.get("size") or t["size"], "fps": tuning.get("fps", 30), "multipass": tuning.get("multipass", "disabled"),
            "capacity": cap, "muxrate": mux, "audio_k": t["audio_k"], "aac_he_v2": t["aac_he_v2"],
            "pcr_ms": t["pcr_ms"], "pat_s": t["pat_s"], "sdt_s": SDT_PERIOD_S,
            "video_bps": round(video * rate), "bufsize": round(bufsize * rate), "rate": rate}


def plan(sr_ks, fec, source):
    s = settings(sr_ks, fec, clock_tuning(sr_ks, fec) if source == "clock" else None)
    return {"capacity_kbps": round(s["capacity"] / 1000), "mux_kbps": round(s["muxrate"] / 1000), "size": s["size"], "fps": s["fps"],
            "video_kbps": round(s["video_bps"] / 1000), "audio_kbps": s["audio_k"], "rate": s["rate"],
            "audio": "AAC-HE v2" if s["aac_he_v2"] else "AAC-LC",
            "encoder": "GPU" if s["encoder"] == "hevc_nvenc" else "software"}


def _video_options(s, size, video, extra):
    """H.265 options: QOCAST's NVENC set on a GPU, otherwise libx265 with the same GOP (100 frames at 30 fps) and rate limits."""
    gop = str(round(100 * s["fps"] / 30))
    if s["encoder"] == "hevc_nvenc":
        return ["-c:v", "hevc_nvenc", *size, "-r", str(s["fps"]),
                "-b_ref_mode", "disabled", "-profile:v", "main", "-pix_fmt", "yuv420p",
                "-preset:v", "p7", "-tune:v", "ll", "-rc:v", "cbr", "-g", gop,
                "-b:v", video, "-minrate", video, "-maxrate", str(int(video) + 1),
                "-bufsize", str(s["bufsize"]), *extra]
    return ["-c:v", "libx265", *size, "-r", str(s["fps"]), "-profile:v", "main", "-pix_fmt", "yuv420p",
            "-preset", x265_preset(s["size"]), "-tune", "zerolatency",
            "-b:v", video, "-maxrate", video, "-bufsize", str(s["bufsize"]),
            "-x265-params", f"keyint={gop}:min-keyint={gop}:scenecut=0:log-level=error"]


def ffmpeg_command(s, inputs, service_name, provider, video_filter=None, audio_filter="lowpass=20000"):
    """QOCAST's build_ffmpeg_command, with the transport stream on stdout. ``inputs`` must give video then audio.
    video_filter: a -vf chain that sets the picture size (stills); without it the frames are scaled with -s like QOCAST."""
    video = str(s["video_bps"])
    audio_profile = "aac_he_v2" if s["aac_he_v2"] else "aac_low"
    size = ["-vf", video_filter] if video_filter else ["-s", s["size"]]
    extra = [] if s["multipass"] == "disabled" else ["-multipass", s["multipass"]]
    return [
        str(FFMPEG), "-nostdin", "-hide_banner", "-loglevel", "warning",
        *inputs,
        *_video_options(s, size, video, extra),
        "-c:a", "libfdk_aac", "-profile:a", audio_profile,
        *(["-af", audio_filter] if audio_filter else []), "-ac", "2", "-b:a", f"{s['audio_k']}k",
        "-ar", "48000", "-pcr_period", str(s["pcr_ms"]),
        "-pat_period", str(s["pat_s"]), "-sdt_period", str(s["sdt_s"]),
        "-max_delay", "1600000", "-mpegts_original_network_id", "100",
        "-mpegts_transport_stream_id", "1", "-mpegts_service_id", "1",
        "-mpegts_pmt_start_pid", "4096", "-mpegts_start_pid", "256",
        "-streamid", "0:256", "-streamid", "1:257",
        "-metadata", f"service_provider={provider}",
        "-metadata", f"service_name={service_name}",
        "-mpegts_flags", "system_b", "-flush_packets", "1",
        "-f", "mpegts", "-muxrate", str(s["muxrate"]), "-",
    ]
