"""Receiver status from datvrx's stderr lines (standard library only).

Parsing and thresholds follow the DATVision Pi player (ui/pi_player/main.py and panels.py).
"""
import collections
import re
import threading
import time

MODULATION = re.compile(r"16APSK|32APSK|8PSK|QPSK|BPSK")
CONSTELLATION_POINTS = 256        # a hardware demodulator gives a few symbols per status read: keep a short history
clamp_byte = lambda value: max(0, min(255, int(round(value))))
REPORT =re.compile(r"(DVB-S2X|DVB-S2|DVB-S) (\S+) (\d+/\d+)\S*(?: short)?(?: pilots)?\s+[\d.]+ Msym/s"
                    r"\s+Es/N0 ([\d.-]+) dB\s+ok \d+\s+bad (\d+)")


def _table(standard, modulation, values):
    return {(standard, modulation, rate): db for rate, db in values}


# Approximate quasi-error-free Es/N0 (dB, AWGN): DVB-S2 from EN 302 307 table 13,
# DVB-S from the EN 300 421 Eb/N0 figures converted to Es/N0.
REQUIRED_ESN0 = {
    **_table("DVB-S", "QPSK", (("1/2", 4.1), ("2/3", 5.9), ("3/4", 6.9), ("5/6", 7.9), ("7/8", 8.5))),
    **_table("DVB-S2", "QPSK", (("1/4", -2.35), ("1/3", -1.24), ("2/5", -0.30), ("1/2", 1.00), ("3/5", 2.23),
                                ("2/3", 3.10), ("3/4", 4.03), ("4/5", 4.68), ("5/6", 5.18), ("8/9", 6.20), ("9/10", 6.42))),
    **_table("DVB-S2", "8PSK", (("3/5", 5.50), ("2/3", 6.62), ("3/4", 7.91), ("5/6", 9.35), ("8/9", 10.69), ("9/10", 10.98))),
    **_table("DVB-S2", "16APSK", (("2/3", 8.97), ("3/4", 10.21), ("4/5", 11.03), ("5/6", 11.61), ("8/9", 12.89), ("9/10", 13.13))),
    **_table("DVB-S2", "32APSK", (("3/4", 12.73), ("4/5", 13.64), ("5/6", 14.28), ("8/9", 15.69), ("9/10", 16.05))),
}

REPORT_STALE_S = 3.0      # reports come every second; silence this long means no lock
CELLS_STALE_S = 1.5       # the constellation is sent four times a second


class ReceiverStatus:
    """Latest lock, quality and constellation of the running receiver; safe across threads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.running = False
            self.ts_lock = False
            self.report_at = self.cells_at = 0.0
            self.mode = self.modulation = ''
            self.esn0 = self.required = self.margin = self.rf_level = None
            self.label = 'Es/N0'
            self.bad = self.lost = 0
            self.cells = ''
            self.points = collections.deque(maxlen=CONSTELLATION_POINTS)

    def set_hardware(self, locked, mode, esn0, margin, bad, rf_level, points, label='MER'):
        """Status of a hardware demodulator (MiniTiouner / PicoTuner), already worked out by its own tables."""
        now = time.monotonic()
        with self.lock:
            if self.ts_lock and not locked:
                self.lost += 1
            self.ts_lock, self.report_at = bool(locked), now
            self.mode = mode or ''
            kind = MODULATION.search(self.mode)
            self.modulation = kind.group(0) if kind else ''
            self.esn0 = esn0 if locked and isinstance(esn0, (int, float)) else None
            self.margin = margin if locked and isinstance(margin, (int, float)) else None
            self.bad = int(bad or 0)
            self.rf_level = rf_level if isinstance(rf_level, (int, float)) else None
            self.label = label
            if locked and points:
                self.points.extend(points)
                self.cells = ''.join('%02x%02x' % (clamp_byte(128 + 64 * i), clamp_byte(128 + 64 * q)) for i, q in self.points)
                self.cells_at = now
            elif not locked:
                self.points.clear()

    def set_running(self, running):
        with self.lock:
            self.running = running

    def feed(self, line):
        now = time.monotonic()
        with self.lock:
            if line.startswith('datvrx cells '):
                self.cells, self.cells_at = line[13:].strip(), now
            elif line.startswith('datvrx ['):
                match = REPORT.search(line)
                if not match:                       # still searching: no standard or Es/N0 yet
                    self.ts_lock, self.report_at, self.esn0 = False, now, None
                    return
                standard, modulation, rate, esn0, bad = match.groups()
                self.modulation, self.esn0, self.bad = modulation, float(esn0), int(bad)
                self.required = REQUIRED_ESN0.get((standard, modulation, rate))
                self.mode = '%s %s %s' % (standard, modulation, rate)
                self.ts_lock, self.report_at = 'TS lock' in line, now
            elif line.strip() == 'datvrx: transport stream lock':
                self.ts_lock, self.report_at = True, now      # at once, without waiting for the next report
            elif 'synchronisation lost' in line:
                self.ts_lock = False
                self.lost += 1

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            fresh = now - self.report_at < REPORT_STALE_S
            locked = self.running and self.ts_lock and fresh
            esn0 = self.esn0 if self.running and fresh else None
            if self.margin is not None:
                margin = self.margin if esn0 is not None else None      # the hardware worked it out itself
            else:
                margin = None if esn0 is None or self.required is None else esn0 - self.required
            return {'running': self.running, 'locked': locked, 'mode': self.mode if fresh else '',
                    'modulation': self.modulation if fresh else '', 'esn0': esn0, 'margin': margin,
                    'esn0_label': self.label, 'rf_level': self.rf_level if self.running and fresh else None,
                    'bad': self.bad, 'lost': self.lost,
                    'cells': self.cells if self.running and now - self.cells_at < CELLS_STALE_S else ''}


def pump(stream, log, status):
    """Copy a receiver's stderr to its log file while feeding the status; ends when the pipe closes."""
    for raw in iter(stream.readline, b''):
        log.write(raw)
        log.flush()
        status.feed(raw.decode('utf-8', 'replace').rstrip('\r\n'))
