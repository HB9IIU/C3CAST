#!/usr/bin/env python3
"""Hardware regression: stream symbols until the ESP's own deadline expires.

Stop the normal transmitter first. This emits RF with PA enable off.
Run on production firmware, or build with -D DATV_TEST_COUNTER_WRAP=ON to
cross byte/symbol counter boundaries after the first 512 input bytes (pass
--counter-wrap to account for the diagnostic counter seed).
Restore a build with DATV_TEST_COUNTER_WRAP=OFF after the diagnostic test.

  python3 host/check_tx_duration.py --output /tmp/tx-duration.json
"""
import argparse
import json
from pathlib import Path
import re
import time

from esp_link import Link, find_port
from tx_dvbs import build_parser, resolve_transmission
from tx_gui_model import load_live_state


CASES = (
    ("qpsk", 1000000), ("qpsk", 500000), ("qpsk", 333000), ("qpsk", 66000),
    ("8psk", 1000000), ("8psk", 250000), ("8psk", 66000),
    ("16apsk", 1000000), ("16apsk", 500000), ("16apsk", 125000),
    ("32apsk", 250000), ("32apsk", 66000),
)


def check(mod, baud, freq, seconds, port, counter_wrap=False):
    fec = "1/2" if mod == "qpsk" else "3/4"
    a = build_parser().parse_args(["--dvbs2", "--mod", mod, "--baud", str(baud), "--fec", fec, "--null"])
    resolve_transmission(a)
    command = {"qpsk": "QPSKT", "8psk": "PSK8T", "16apsk": "A16T", "32apsk": "A32T"}[mod]
    gamma = " 284 527" if mod == "32apsk" else " 285" if mod == "16apsk" else ""
    link = Link(find_port(port))
    try:
        link.configure_pa(False)
        ack = link.start(f"{command} {freq:.3f} {baud} {a.sps} 60 {seconds} 0 {a.target} 0 0 10000 0{gamma}")
        started = time.monotonic()
        fills = []
        payload = bytes(range(32)) * 256 if mod == "32apsk" else bytes(range(256)) * 32
        full_packets = (mod == "16apsk" and baud == 1000000) or (mod == "32apsk" and baud == 250000)
        min_todo, chunk = ((400, 4096) if mod == "16apsk" and baud == 1000000 else
                           (400, 2048) if mod == "8psk" and baud == 1000000 else
                           (64, 2048) if full_packets else (32, 1024))
        while time.monotonic() - started < seconds + 2:
            link.poll()
            if b"TX END" in link.text:
                break
            if link.reports and time.monotonic() - started > .3:
                fills.append(link.fill)
            todo = a.target - (link.fill + link.sent_since)
            if todo >= min_todo:
                count = 2 * min(todo, chunk)
                if full_packets:
                    count -= count % 64
                if count:
                    link.send(payload[:count])
                    link.sent_since += count // 2
            else:
                time.sleep(.0005)
        elapsed = time.monotonic() - started
        summary = link.finish(send_stop=False)
        counters = re.search(r"bytes_in=(\d+).*buffer=(\d+) pairs", summary)
        symbols_per_byte = (8 / 3 if mod == "8psk" and a.sps == 8 else
                            1 if mod == "32apsk" else 2 if mod != "qpsk" else 4)
        # ACK precedes prefill and tuning on CLEAN_TX firmware. Check the
        # consumed payload against the requested on-air duration, independently
        # of that variable startup delay. One packed record may be in flight.
        shift = 0 if a.sps == 8 else 2 if mod == "qpsk" else 1
        seed = ((0xffffffff >> shift) - 511) if counter_wrap and mod != "32apsk" else 0
        received = (int(counters[1]) - seed) & 0xffffffff if counters else 0
        consumed = received - 2 * int(counters[2]) if counters else 0
        air_seconds = consumed * symbols_per_byte / baud
        block = 2056 if a.sps == 8 and mod in ("8psk", "16apsk") else 2051
        timing_ok = (seconds - .003 <= air_seconds <= seconds + block / baud + .003)
        return dict(mod=mod, baud=baud, sps=a.sps, ack=ack, elapsed=elapsed,
                    air_seconds=air_seconds,
                    min_fill=min(fills) if fills else None, max_fill=max(fills) if fills else None,
                    summary=summary, passed=timing_ok and seconds <= elapsed < seconds + 3.2 and "TX END" in summary
                    and bool(fills) and min(fills) > 0)
    finally:
        if link.s.is_open:
            link.s.close()  # loss-of-input timeout shuts down RF even on a failed test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freq", type=float, default=2405.216, help="MHz; no PPM correction")
    parser.add_argument("--seconds", type=int, default=3)
    parser.add_argument("--port")
    parser.add_argument("--counter-wrap", action="store_true", help="firmware built with DATV_TEST_COUNTER_WRAP=ON")
    args = parser.parse_args()
    if not 2300 <= args.freq <= 2450 or not 1 <= args.seconds <= 60:
        parser.error("frequency: 2300..2450 MHz; duration: 1..60 seconds")
    if load_live_state():
        parser.error("Stop the current transmitter before running the hardware test")
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for mod, baud in CASES:
        result = check(mod, baud, args.freq, args.seconds, args.port, args.counter_wrap)
        results.append(result)
        args.output.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(result), flush=True)
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
