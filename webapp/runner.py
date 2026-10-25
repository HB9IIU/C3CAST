"""Runs upstream host/tx_dvbs.py unchanged, but turns a Windows CTRL_BREAK (or SIGTERM) into
the same clean-stop path as Ctrl-C, so the transmitter is muted and the ESP reports TX END.

It also leaves with os._exit after the work is done: with `--ts -` upstream's stdin reader thread is still
blocked in read(), and normal interpreter shutdown then dies with "Fatal Python error" (exit 0xC0000005).
"""
import os
import signal
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host"))


def _stop(signum, frame):
    raise KeyboardInterrupt


for name in ("SIGBREAK", "SIGTERM"):
    if hasattr(signal, name):
        signal.signal(getattr(signal, name), _stop)

import tx_dvbs  # noqa: E402

code = 0
try:
    tx_dvbs.main(sys.argv[1:])
except SystemExit as e:                     # upstream reports problems as SystemExit("message")
    if isinstance(e.code, int):
        code = e.code
    elif e.code is not None:
        print(e.code, file=sys.stderr)
        code = 1
except BaseException:
    traceback.print_exc()
    code = 1
sys.stdout.flush()
sys.stderr.flush()
os._exit(code)
