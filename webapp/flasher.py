"""Flashing the bundled firmware (webapp/firmware/, made by tools/export_firmware.py) with esptool.
Only ever on a port the user picked; the whole flash is erased first, so a blank board and an old one end up the same."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import paths

FIRMWARE = paths.RESOURCE / "firmware"
BAUD = "460800"


def manifest():
    return json.loads((FIRMWARE / "manifest.json").read_text())


def check_bundle():
    """(ok, text, manifest or None): every file present with the right size and SHA-256."""
    try:
        m = manifest()
    except (OSError, ValueError):
        return False, "firmware bundle missing: run tools/export_firmware.py", None
    for f in m["files"]:
        path = FIRMWARE / f["file"]
        if not path.is_file() or path.stat().st_size != f["size"] or hashlib.sha256(path.read_bytes()).hexdigest() != f["sha256"]:
            return False, f"firmware file {f['file']} is missing or changed", m
    return True, f"{m['name']} (C3CAST {m['c3cast_version']})", m


def command(port, m):
    """esptool: erase everything, write bootloader, partition table and app, then reset the board."""
    fl = m["flash"]
    cmd = [*paths.worker_cmd("esptool"), "--chip", m["chip"], "--port", port, "--baud", BAUD,
           "--before", "default-reset", "--after", "hard-reset",
           "write-flash", "--erase-all", "--flash-mode", fl["mode"], "--flash-freq", fl["freq"], "--flash-size", fl["size"]]
    for f in m["files"]:
        cmd += [f["offset"], str(FIRMWARE / f["file"])]
    return cmd


def popen(port, m):
    return subprocess.Popen(command(port, m), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def percent(line):
    """Progress of the current write ("Writing at 0x0003b4e0 [====>   ]  45.2% ..." in esptool 5), or None."""
    m = PERCENT.search(line) if line.startswith("Writing at") else None
    return int(float(m.group(1))) if m else None
