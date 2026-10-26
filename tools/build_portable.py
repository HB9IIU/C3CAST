"""Builds the portable Windows package:  dist/C3CAST-Portable-x64-<version>/  and the same as a .zip.

    .venv-host\\Scripts\\python.exe tools\\export_firmware.py      (only if the firmware changed)
    .venv-host\\Scripts\\python.exe tools\\build_portable.py

Needs pyinstaller in the venv. tools/ffmpeg/bin/ffmpeg.exe (GPL build: x265, NVENC, native AAC) is copied into the package. Before
the package is given to anyone, ffmpeg's matching source and notices must be added (see docs/RELEASE_CHECKLIST.md).
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "webapp"))
import version  # noqa: E402

NAME = f"C3CAST-Portable-x64-{version.__version__}"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
OUT = DIST / NAME
sep = ";"                                                       # --add-data separator on Windows

data = [("webapp/templates", "templates"), ("webapp/static", "static"), ("webapp/fonts", "fonts"),
        ("webapp/firmware", "firmware"), ("webapp/testcards", "testcards"),
        ("host/dvbs2_ldpc.json", "."), ("host/cal.json", ".")]          # read next to their module by upstream's host code
hidden = ["runner", "stream_tx", "clock_card", "camera", "qo100_enc", "flasher", "paths", "version",
          "tx_dvbs", "tx_media", "dvbs", "dvbs2", "esp_link", "serial.tools.list_ports_windows"]

if not (ROOT / "webapp" / "firmware" / "manifest.json").is_file():
    sys.exit("run tools/export_firmware.py first")
for p in (BUILD, OUT):
    shutil.rmtree(p, ignore_errors=True)

cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--name", "C3CAST", "--icon", str(ROOT / "webapp" / "static" / "c3cast.ico"),
       "--distpath", str(BUILD / "pyi-dist"), "--workpath", str(BUILD / "pyi-work"), "--specpath", str(BUILD),
       "--paths", str(ROOT / "webapp"), "--paths", str(ROOT / "host"), "--collect-all", "esptool"]
for src, dest in data:
    cmd += ["--add-data", f"{ROOT / src}{sep}{dest}"]
for h in hidden:
    cmd += ["--hidden-import", h]
cmd.append(str(ROOT / "webapp" / "c3cast.py"))
print("running PyInstaller ...", flush=True)
subprocess.run(cmd, check=True)

shutil.copytree(BUILD / "pyi-dist" / "C3CAST", OUT)
ff = ROOT / "tools" / "ffmpeg"
if not (ff / "bin" / "ffmpeg.exe").is_file():
    sys.exit("tools/ffmpeg/bin/ffmpeg.exe is missing")
(OUT / "tools" / "ffmpeg" / "bin").mkdir(parents=True)
shutil.copy2(ff / "bin" / "ffmpeg.exe", OUT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe")
# the old notices in tools/ffmpeg/licenses describe the previous (FDK) build; the package gets the notice for this GPL build
lic = OUT / "tools" / "ffmpeg" / "licenses"
shutil.copytree(ff / "licenses", lic, ignore=shutil.ignore_patterns("FDK-AAC-NOTICE.txt", "FFmpeg-NOTICE.txt"))
shutil.copy2(ROOT / "docs" / "FFMPEG-NOTICE.txt", lic / "FFmpeg-NOTICE.txt")
shutil.copy2(ff / "buildconf.txt", lic / "buildconf.txt")
shutil.copy2(ROOT / "docs" / "FFMPEG-NOTICE.txt", OUT / "tools" / "ffmpeg" / "README.txt")
shutil.copytree(ff / "source", OUT / "tools" / "ffmpeg" / "source")      # the GPL source travels inside the package
(OUT / "pictures").mkdir()
for pic in (ROOT / "webapp" / "pictures").iterdir():
    if pic.is_file():
        shutil.copy2(pic, OUT / "pictures" / pic.name)
shutil.copy2(ROOT / "LICENSE", OUT / "LICENSE")
shutil.copy2(ROOT / "LICENSE.upstream", OUT / "LICENSE-firmware-SP8ESA.txt")
(OUT / "README-PORTABLE.txt").write_text(
    f"C3CAST {version.__version__} by HB9IIU: the 5 EUR DATV modulator. Plug, flash, play.\r\n"
    "\r\n"
    "1. Double-click C3CAST.exe. A window opens (close it to quit) and your browser opens the page.\r\n"
    "2. Plug the Seeed XIAO ESP32-C3 into USB. If the page does not say 'board connected', press Flash.\r\n"
    "3. Pick a picture, the SBB clock or a USB camera, choose symbol rate and FEC, press Start.\r\n"
    "\r\n"
    "Your own pictures go in the 'pictures' folder (PNG or JPG, 16:9, 1280x720 is ideal).\r\n"
    "Your settings are saved in config.json next to C3CAST.exe.\r\n"
    "\r\n"
    "Licensed radio amateurs only. Use a filter before any amplifier and check the spectrum first.\r\n"
    "\r\n"
    "Licence: PolyForm Noncommercial 1.0.0. LICENSE covers C3CAST (HB9IIU); LICENSE-firmware-SP8ESA.txt covers the\r\n"
    "ESP32-DATV firmware by SP8ESA that C3CAST flashes to the board.\r\n"
    "ffmpeg (in the tools folder) is a GPL build: its licence, notices and where to get its source are in tools/ffmpeg/README.txt.\r\n",
    encoding="utf-8")

zip_path = shutil.make_archive(str(DIST / NAME), "zip", DIST, NAME)
size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
print(f"\nbuilt {OUT}  ({size:.0f} MB)\nzip   {zip_path}  ({Path(zip_path).stat().st_size / 1e6:.0f} MB)")
