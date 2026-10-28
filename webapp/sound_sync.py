"""Sound sync: how much later a camera's sound comes than its picture (ported from HB9IIU/QOCAST, sound_sync.py).

The user claps 6-8 times in front of the camera (not in a steady rhythm: then a shift by one beat would match as well). From a
recording of the camera and its microphone, as one DirectShow input like on air:

- picture: how much each frame differs from the previous one (signalstats YDIF)
- sound:   loudness every 10 ms (astats RMS)

Both curves are compared at every shift from -1000 to +1000 ms; the best match is the offset. Positive = the sound comes later
than the picture. C3CAST's delay control has the opposite sign (plus delays the sound), so the delay to apply is -offset.
Experimental: the recording shows only the camera and microphone, not what a receiver adds.
"""

import math
import re
import subprocess

from qo100_enc import FFMPEG as FFMPEG_EXE

RECORD_SECONDS = 12
STEP_S = 0.010          # one sample every 10 ms
MAX_SHIFT_MS = 1000
MIN_SCORE = 0.3         # below: no clear claps (measured: claps 0.4-0.5, none 0.04)
ROUND_MS = 10
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _metadata(path, args, key):
    """[(time s, value)] from FFmpeg's metadata=print for ``key``."""
    out = subprocess.run([str(FFMPEG_EXE), "-hide_banner", "-nostats", "-i", str(path), *args,
                          "-f", "null", "-"],
                         capture_output=True, text=True, errors="replace", creationflags=_NO_WINDOW).stderr
    points, t = [], None
    for line in out.splitlines():
        if m := re.search(r"pts_time:(\S+)", line):
            t = float(m[1])
        elif t is not None and (m := re.search(re.escape(key) + r"=(\S+)", line)):
            points.append((t, float(m[1])))
    return points


def picture_motion(path):
    return _metadata(path, ["-an", "-vf", "scale=320:-2,signalstats,metadata=mode=print:key=lavfi.signalstats.YDIF"],
                     "lavfi.signalstats.YDIF")


def sound_level(path):
    # 480 samples at 48 kHz = 10 ms; RMS in dB, -inf for silence
    points = _metadata(path, ["-vn", "-af", "aresample=48000,asetnsamples=n=480:p=0,"
                              "astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
                              "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level"],
                       "lavfi.astats.Overall.RMS_level")
    return [(t, 10 ** (db / 20) if math.isfinite(db) else 0.0) for t, db in points]


def _on_grid(points, start, count, hold):
    """Values every STEP_S from ``start``; each point is kept for ``hold`` s."""
    grid = [0.0] * count
    for t, value in points:
        first = round((t - start) / STEP_S)
        for i in range(max(first, 0), min(first + max(1, round(hold / STEP_S)), count)):
            grid[i] = max(grid[i], value)
    return grid


def _normalised(values):
    mean = sum(values) / len(values)
    spread = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) or 1.0
    return [(v - mean) / spread for v in values]


def match(motion, level):
    """[(score, shift ms)], best first, for picture motion and sound level points."""
    fps = (len(motion) - 1) / (motion[-1][0] - motion[0][0])
    start = min(motion[0][0], level[0][0])
    count = round((max(motion[-1][0], level[-1][0]) - start) / STEP_S) + 1
    picture = _normalised(_on_grid(motion, start, count, 1 / fps))
    # the sound averaged over one frame time, like the picture
    raw = _on_grid(level, start, count, STEP_S)
    width = max(1, round(1 / fps / STEP_S))
    sound = _normalised([sum(raw[i:i + width]) / width for i in range(count)])
    scores = []
    for lag in range(-MAX_SHIFT_MS // 10, MAX_SHIFT_MS // 10 + 1):
        pairs = [(picture[i], sound[i + lag]) for i in range(max(0, -lag), min(count, count - lag))]
        scores.append((sum(p * s for p, s in pairs) / len(pairs), lag * 10))
    return sorted(scores, reverse=True)


def measure(path):
    """dict(offset_ms, score, runner_up, clear) for a recording with claps.
    ``clear`` False: no clear claps (too soft, out of view, or a steady rhythm)."""
    motion, level = picture_motion(path), sound_level(path)
    if len(motion) < 30 or len(level) < 100:
        raise RuntimeError(f"The recording is too short ({len(motion)} frames, "
                           f"{len(level) / 100:.1f} s of sound) - is the microphone working?")
    ranked = match(motion, level)
    (score, shift) = ranked[0]
    runner_up = next(r for r in ranked if abs(r[1] - shift) > 100)[0]
    return dict(offset_ms=round(shift / ROUND_MS) * ROUND_MS, score=round(score, 2),
                runner_up=round(runner_up, 2),
                clear=score >= MIN_SCORE and runner_up <= 0.8 * score)
