"""Where things live, for both ways of running C3CAST.

From source (python webapp/app.py):  bundled files are in webapp/, your files too, tools in <project>/tools.
Portable exe (C3CAST.exe):           bundled read-only files are in _internal/ (RESOURCE); your files (config.json, pictures/,
                                     overlays/) and tools/ffmpeg sit next to C3CAST.exe (DATA, TOOLS), so they survive an update.

Helpers (the transmitter, the flasher) are started as separate processes. From source they are python scripts; in the exe they
are C3CAST.exe itself with --worker <name> (see c3cast.py), because there is no python to call.
"""
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    RESOURCE = Path(sys._MEIPASS)
    DATA = Path(sys.executable).resolve().parent
    TOOLS = DATA / "tools"
    PLAYER = DATA / "H266-Player"                  # the optional HB9IIU Experimental H.266 Player, next to C3CAST.exe
else:
    RESOURCE = Path(__file__).resolve().parent
    DATA = RESOURCE
    TOOLS = RESOURCE.parent / "tools"
    PLAYER = TOOLS / "h266-player"


def worker_cmd(name):
    """Command prefix that runs a helper: 'stream_tx', 'runner' or 'esptool'."""
    if FROZEN:
        return [sys.executable, "--worker", name]
    if name == "esptool":
        return [sys.executable, "-u", "-m", "esptool"]
    return [sys.executable, "-u", str(RESOURCE / f"{name}.py")]
