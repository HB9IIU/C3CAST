"""SBB clock testcard, ported from the Jetson's funnyClock/clock_tx.py.

A PM5544-style card with a station clock: the static background is drawn
once with Pillow, the hands and the "... Hz" label for every frame. Frames
are written as raw RGB to FFmpeg's stdin; the tones come from an FFmpeg
aevalsrc expression keyed to the same start time, so picture and sound stay
in step.
"""

import datetime
import math
import time

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Copied from HB9IIU/QOCAST clock_card.py. Only change: FONT_DIR (QOCAST's runtime_paths) is local here.
FONT_DIR = Path(__file__).resolve().parent / "fonts"

WIDTH, HEIGHT = 1280, 720       # the layout below is drawn for 720p
FPS = 30
FONT_PATH = FONT_DIR / "VarelaRound-Regular.ttf"

# Tone per 5-second dial mark of every minute, each playing for TONE_SECONDS;
# before :05 it's silent. A BEEP_HZ time signal plays when the minute jumps.
TONE_SECONDS = 1.0
TONE_SCHEDULE = [(5, 300), (10, 400), (15, 600), (20, 800), (25, 1000), (30, 1200),
                 (35, 1000), (40, 800), (45, 600), (50, 400), (55, 300)]
TONE_VOLUME = 0.126             # linear, ~ -18 dBFS
BEEP_HZ = 1000
# The SBB second hand sweeps the dial in 58.5 s, then waits for the minute.
SWEEP_SECONDS = 58.5
# The clock (hands and tones) runs this far ahead, so it shows real time when
# it reaches the viewer (measured on the Jetson to MiniTioune: 4.5-5.1 s).
CLOCK_AHEAD_SECONDS = 5.0

CARD_GREY = "#6e6e6e"
RIM_COLOR = "#b4b8bc"
SBB_RED = (0xe0, 0x20, 0x20)
TEXT_COLOR = "#3c4650"

cx, cy = WIDTH // 2, HEIGHT // 2
radius = 300                    # white dial, in output pixels
RIM = 12                        # silver bezel width
SS = 3                          # supersampling factor for the static dial
HAND_SS = 2                     # supersampling factor for the moving hands
GRID = 60                       # test card grid pitch
EDGE = 20                       # height of the black/white edge blocks

BARS = [(191, 191, 191), (191, 191, 0), (0, 191, 191), (0, 191, 0),
        (191, 0, 191), (191, 0, 0), (0, 0, 191), (0, 0, 0)]
GREY_STEPS = [255, 204, 153, 102, 51, 0]
GRATING_WIDTHS = [4, 3, 2, 1]

LABEL_SIZE = 30
CALLSIGN_SIZE = 54
LOCATOR_SIZE = 42
TAG_TEXT = "ESP32 DATV"           # under the callsign, sized to the callsign's width (changed from QOCAST's brand line)
LABEL_Y = 0.54                  # label centre below the dial centre, x radius

HALF = radius + RIM + 4         # half size of the square box around the dial


def _font(size):
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except OSError:
        return ImageFont.truetype("arialbd.ttf", size)


def _centered_text(draw, x, y, text, font, fill):
    left, top, right, bottom = font.getbbox(text)
    draw.text((x - (left + right) / 2, y - (top + bottom) / 2), text, font=font, fill=fill)


def _build_card():
    card = Image.new("RGB", (WIDTH, HEIGHT), CARD_GREY)
    draw = ImageDraw.Draw(card)
    for x in range(cx % GRID, WIDTH, GRID):
        draw.rectangle((x - 1, 0, x, HEIGHT), fill="white")
    for y in range(cy % GRID, HEIGHT + 1, GRID):
        draw.rectangle((0, y - 1, WIDTH, y), fill="white")
    for i, x in enumerate(range(cx % GRID - GRID, WIDTH, GRID)):
        fill = "black" if i % 2 else "white"
        draw.rectangle((x, 0, x + GRID - 1, EDGE - 1), fill=fill)
        draw.rectangle((x, HEIGHT - EDGE, x + GRID - 1, HEIGHT - 1), fill=fill)

    top, bottom = cy - 4 * GRID, cy + 4 * GRID
    left_x0, left_x1 = cx - 10 * GRID, cx - 6 * GRID
    right_x0, right_x1 = cx + 6 * GRID, cx + 10 * GRID
    for x0, x1 in ((left_x0, left_x1), (right_x0, right_x1)):
        draw.rectangle((x0 - 2, top - 2, x1 + 1, bottom + 1), fill="black")
    for i, colour in enumerate(BARS):
        y = top + i * GRID
        draw.rectangle((left_x0, y, left_x1 - 1, y + GRID - 1), fill=colour)
    step = (right_x1 - right_x0) // len(GREY_STEPS)
    for i, level in enumerate(GREY_STEPS):
        x = right_x0 + i * step
        draw.rectangle((x, top, x + step - 1, cy - 1), fill=(level, level, level))
    for row, width in enumerate(GRATING_WIDTHS):
        y = cy + row * GRID
        for x in range(right_x0, right_x1, 2 * width):
            draw.rectangle((x, y, x + width - 1, y + GRID - 1), fill="white")
    return card


def render_background(callsign, locator):
    """Card with dial, markers, callsign and locator (anti-aliased)."""
    card = _build_card()
    box = 2 * HALF * SS
    R = radius * SS
    C = box / 2
    face = card.crop((cx - HALF, cy - HALF, cx + HALF, cy + HALF))
    face = face.resize((box, box), Image.NEAREST)
    draw = ImageDraw.Draw(face)

    def disc(r, fill):
        draw.ellipse((C - r, C - r, C + r, C + r), fill=fill)

    def marker(angle, r_from, r_to, w):
        px, py = math.cos(angle), math.sin(angle)
        dx, dy = math.sin(angle), -math.cos(angle)
        a = w * R / 2
        x0, y0 = C + dx * r_from * R, C + dy * r_from * R
        x1, y1 = C + dx * r_to * R, C + dy * r_to * R
        draw.polygon([(x0 - px * a, y0 - py * a), (x1 - px * a, y1 - py * a),
                      (x1 + px * a, y1 + py * a), (x0 + px * a, y0 + py * a)], fill="black")

    disc(R + (RIM + 3) * SS, "black")
    disc(R + RIM * SS, RIM_COLOR)
    disc(R, "white")
    for i in range(60):
        angle = 2 * math.pi * i / 60
        if i % 5 == 0:
            marker(angle, 0.75, 0.97, 0.065)
        else:
            marker(angle, 0.90, 0.97, 0.024)
    call_font = _font(CALLSIGN_SIZE * SS)
    _centered_text(draw, C, C - 0.45 * R, callsign, call_font, TEXT_COLOR)
    call_left, _, call_right, _ = call_font.getbbox(callsign)
    probe_left, _, probe_right, _ = call_font.getbbox(TAG_TEXT)
    tag_size = max(1, round(CALLSIGN_SIZE * SS * (call_right - call_left) / (probe_right - probe_left)))
    _centered_text(draw, C, C - 0.31 * R, TAG_TEXT, _font(tag_size), TEXT_COLOR)
    _centered_text(draw, C, C + 0.40 * R, locator, _font(LOCATOR_SIZE * SS), TEXT_COLOR)
    card.paste(face.resize((2 * HALF, 2 * HALF), Image.BOX), (cx - HALF, cy - HALF))
    return card


def sound_at(wall_time):
    """Tone frequency at this wall-clock time (0 = silence)."""
    second = wall_time % 60
    if second < TONE_SECONDS:
        return BEEP_HZ
    # Tones follow the red second hand, which sweeps in SWEEP_SECONDS.
    for mark, freq in TONE_SCHEDULE:
        start = mark * SWEEP_SECONDS / 60
        if start <= second < start + TONE_SECONDS:
            return freq
    return 0


def tone_expression(start_wall_time):
    """aevalsrc expression playing the clock tones; ``t`` = 0 at start_wall_time."""
    s = f"mod(t+{(start_wall_time + CLOCK_AHEAD_SECONDS) % 60:.3f},60)"
    parts = [f"lt({s},{TONE_SECONDS:g})*sin(2*PI*{BEEP_HZ}*t)"]
    for mark, freq in TONE_SCHEDULE:
        start = mark * SWEEP_SECONDS / 60
        parts.append(f"gte({s},{start:g})*lt({s},{start + TONE_SECONDS:g})*sin(2*PI*{freq}*t)")
    return f"{TONE_VOLUME}*({'+'.join(parts)})"


class ClockRenderer:
    """Draws clock frames; the dial area is redrawn supersampled each frame."""

    def __init__(self, callsign, locator):
        self.background = render_background(callsign, locator)
        dial = self.background.crop((cx - HALF, cy - HALF, cx + HALF, cy + HALF))
        self._dial_hi = dial.resize((2 * HALF * HAND_SS,) * 2, Image.BICUBIC)
        self._label_font = _font(LABEL_SIZE * HAND_SS)

    def frame(self, wall_time):
        """RGB image of the clock as it should look at ``wall_time``."""
        now = wall_time + CLOCK_AHEAD_SECONDS
        dial = self._dial_hi.copy()
        draw = ImageDraw.Draw(dial)
        c = HALF * HAND_SS
        r = radius * HAND_SS

        freq = sound_at(now)
        if freq:
            _centered_text(draw, c, c + LABEL_Y * r, f"{freq} Hz", self._label_font, TEXT_COLOR)

        def hand(angle, r_from, r_to, w_from, w_to, fill):
            px, py = math.cos(angle), math.sin(angle)
            dx, dy = math.sin(angle), -math.cos(angle)
            x0, y0 = c + dx * r_from * r, c + dy * r_from * r
            x1, y1 = c + dx * r_to * r, c + dy * r_to * r
            a, b = w_from * r / 2, w_to * r / 2
            draw.polygon([(x0 - px * a, y0 - py * a), (x1 - px * b, y1 - py * b),
                          (x1 + px * b, y1 + py * b), (x0 + px * a, y0 + py * a)], fill=fill)

        local = datetime.datetime.fromtimestamp(now)
        second = now % 60
        hour_angle = 2 * math.pi * (local.hour % 12 + local.minute / 60) / 12
        minute_angle = 2 * math.pi * local.minute / 60
        second_angle = 2 * math.pi * min(second / SWEEP_SECONDS, 1.0)
        hand(hour_angle, -0.20, 0.64, 0.12, 0.095, "black")
        hand(minute_angle, -0.20, 0.90, 0.095, 0.07, "black")
        hand(second_angle, -0.30, 0.60, 0.022, 0.022, SBB_RED)
        bx = c + math.sin(second_angle) * 0.60 * r
        by = c - math.cos(second_angle) * 0.60 * r
        draw.ellipse((bx - 0.10 * r, by - 0.10 * r, bx + 0.10 * r, by + 0.10 * r), fill=SBB_RED)

        image = self.background.copy()
        image.paste(dial.reduce(HAND_SS), (cx - HALF, cy - HALF))
        return image


def frame_feeder(renderer, start_wall_time, fps=FPS):
    """Return a function that writes real-time raw RGB frames to FFmpeg."""

    def feed(stdin, stop_event):
        n = 0
        while not stop_event.is_set():
            frame_time = start_wall_time + n / fps
            data = renderer.frame(frame_time).tobytes()
            delay = frame_time - time.time()
            if delay > 0:
                stop_event.wait(delay)
            try:
                stdin.write(data)
            except (BrokenPipeError, OSError, ValueError):
                return
            n += 1

    return feed
