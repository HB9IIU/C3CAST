"""Copies the PlatformIO build outputs into webapp/firmware/ (what the web app flashes) and writes manifest.json.
Run after every firmware build:  .venv-host\\Scripts\\python.exe tools\\export_firmware.py"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / ".pio" / "build" / "seeed_xiao_esp32c3"
OUT = ROOT / "webapp" / "firmware"
sys.path.insert(0, str(ROOT / "webapp"))
import version  # noqa: E402

# offset, source file, bundled name (flash settings from the build's flasher_args.json: dio, 4MB, 80m)
FILES = [("0x0", "bootloader.bin"), ("0x8000", "partitions.bin"), ("0x10000", "firmware.bin")]

OUT.mkdir(exist_ok=True)
files = []
for offset, name in FILES:
    src = BUILD / name
    if not src.is_file():
        sys.exit(f"missing build output {src}: run `pio run` first")
    shutil.copy2(src, OUT / name)
    files.append({"offset": offset, "file": name, "size": src.stat().st_size,
                  "sha256": hashlib.sha256(src.read_bytes()).hexdigest()})
manifest = {
    "name": "ESP32-DATV firmware (SP8ESA) for the XIAO ESP32-C3, PTT on GPIO10 (D10)",
    "c3cast_version": version.__version__,
    "chip": "esp32c3",
    "flash": {"mode": "dio", "freq": "80m", "size": "4MB"},
    "files": files,
}
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
shutil.copy2(ROOT / "LICENSE.upstream", OUT / "LICENSE-PolyForm-Noncommercial-SP8ESA.txt")
(OUT / "README.txt").write_text(
    "Firmware images flashed by the C3CAST web app (Flash button).\n\n"
    "Built from this project's src/ (PlatformIO, ESP-IDF 6.1.0): SP8ESA's ESP32-DATV firmware, upstream commit 915e62d,\n"
    "with the PTT/PA output moved from GPIO3 to GPIO10 (D10). Regenerate with tools/export_firmware.py after a build.\n\n"
    "Licence: PolyForm Noncommercial License 1.0.0, Required Notice: Copyright (c) 2026 SP8ESA (https://github.com/SP8ESA).\n"
    "Noncommercial use only. Anyone who receives these files must receive the licence text (see the LICENSE file here)\n"
    "and keep the Required Notice.\n")
print(f"exported to {OUT}")
for f in files:
    print(f"  {f['offset']:>8} {f['file']:<16} {f['size']:>7} bytes  {f['sha256'][:16]}...")
