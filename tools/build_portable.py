"""Builds the portable Windows package:  dist/C3CAST-Portable-x64-<version>/  and the same as a .zip.

    .venv-host\\Scripts\\python.exe tools\\export_firmware.py      (only if the firmware changed)
    .venv-host\\Scripts\\python.exe tools\\build_portable.py

Needs pyinstaller in the venv. tools/ffmpeg/bin/ffmpeg.exe (GPL build: x265, NVENC, native AAC) is copied into the package. Before
the package is given to anyone, ffmpeg's matching source and notices must be added (see docs/RELEASE_CHECKLIST.md).
"""
import shutil
import hashlib
import subprocess
import sys
import time
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
        ("webapp/firmware", "firmware"), ("webapp/testcards", "testcards"), ("webapp/sources", "sources"),
        ("host/dvbs2_ldpc.json", "."), ("host/cal.json", ".")]
hidden = ["runner", "stream_tx", "clock_card", "camera", "qo100_enc", "flasher", "paths", "version",
          "receivers", "tuner_assignment", "webplayer", "tuners", "rx_status", "ts_info", "usb_devices",
          "window_session", "single_instance", "cpu_load", "tuner_access",
          "tx_dvbs", "tx_media", "dvbs", "dvbs2", "esp_link", "serial.tools.list_ports_windows"]

if not (ROOT / "webapp" / "firmware" / "manifest.json").is_file():
    sys.exit("run tools/export_firmware.py first")
# Never remove a previously tested portable folder or its user settings.
# Keep it next to the new build as an automatic backup.
if OUT.exists():
    backup = DIST / f"{NAME}-backup-{time.strftime('%Y%m%d-%H%M%S')}"
    if OUT.resolve().parent != DIST.resolve() or backup.resolve().parent != DIST.resolve() or backup.exists():
        sys.exit("refusing an unexpected or occupied portable backup path")
    OUT.rename(backup)
    print(f"preserved previous portable folder: {backup}", flush=True)
if BUILD.resolve().parent != ROOT.resolve():
    sys.exit(f"refusing to remove unexpected build path: {BUILD}")
shutil.rmtree(BUILD, ignore_errors=True)

receiver_assets = BUILD / "receiver-assets"
shutil.copytree(ROOT / "webapp" / "receiver", receiver_assets,
                ignore=shutil.ignore_patterns("__pycache__", "obj", "*.log", "*.pdb"))
data.append((str(receiver_assets), "receiver"))

cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--name", "C3CAST", "--icon", str(ROOT / "webapp" / "static" / "c3cast.ico"),
       "--distpath", str(BUILD / "pyi-dist"), "--workpath", str(BUILD / "pyi-work"), "--specpath", str(BUILD),
       "--paths", str(ROOT / "webapp"), "--paths", str(ROOT / "webapp" / "receiver"),
       "--paths", str(ROOT / "host"), "--collect-all", "esptool"]
for src, dest in data:
    cmd += ["--add-data", f"{ROOT / src}{sep}{dest}"]
for h in hidden:
    cmd += ["--hidden-import", h]
cmd.append(str(ROOT / "webapp" / "c3cast.py"))
print("running PyInstaller ...", flush=True)
subprocess.run(cmd, check=True)

shutil.copytree(BUILD / "pyi-dist" / "C3CAST", OUT)
# .NET build leftovers (obj/) hold paths of the build PC and are not needed to run: never ship them
for leftover in list((OUT / "_internal" / "receiver").rglob("obj")):
    if leftover.is_dir():
        shutil.rmtree(leftover)
        print(f"removed build leftover from the package: {leftover.relative_to(OUT)}", flush=True)
ff = ROOT / "tools" / "ffmpeg"
if not (ff / "bin" / "ffmpeg.exe").is_file():
    sys.exit("tools/ffmpeg/bin/ffmpeg.exe is missing")
(OUT / "tools" / "ffmpeg" / "bin").mkdir(parents=True)
shutil.copy2(ff / "bin" / "ffmpeg.exe", OUT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe")
# the old notices in tools/ffmpeg/licenses describe the previous (FDK) build; the package gets the notice for this GPL build
lic = OUT / "tools" / "ffmpeg" / "licenses"
shutil.copytree(ff / "licenses", lic, ignore=shutil.ignore_patterns("FDK-AAC-NOTICE.txt", "FFmpeg-NOTICE.txt", "BUILD-SUPPLIER-NOTICE.txt"))
shutil.copy2(ROOT / "docs" / "FFMPEG-NOTICE.txt", lic / "FFmpeg-NOTICE.txt")
shutil.copy2(ff / "buildconf.txt", lic / "buildconf.txt")
shutil.copy2(ROOT / "docs" / "FFMPEG-THIRD-PARTY-LICENSES.txt", lic / "THIRD-PARTY-LICENSES.txt")
shutil.copy2(ROOT / "docs" / "FFMPEG-NOTICE.txt", OUT / "tools" / "ffmpeg" / "README.txt")
shutil.copytree(ff / "source", OUT / "tools" / "ffmpeg" / "source")      # the GPL source travels inside the package
if (ROOT / "tools" / "h266-player").is_dir():                      # the optional H.266 Player: its own folder, its own licences and source
    # never the player's own logs or settings: it writes them next to its exe while it runs (they hold the tuner's serial number)
    shutil.copytree(ROOT / "tools" / "h266-player", OUT / "H266-Player", ignore=shutil.ignore_patterns("*.log", "player2.json"))
(OUT / "pictures").mkdir()
(OUT / "videos").mkdir()
shutil.copy2(ROOT / "docs" / "VIDEO-CREDITS.txt", OUT / "videos" / "CREDITS.txt")
SAMPLE_FILMS = ("Bunny.mp4", "sintel_trailer.mp4")        # only these ship: anything else in webapp/videos is the developer's own test material
for clip in SAMPLE_FILMS:
    shutil.copy2(ROOT / "webapp" / "videos" / clip, OUT / "videos" / clip)
# Explicit release artwork only: never bundle private test pictures.
SAMPLE_PICTURES = ("C3CAST_ ESP32-C3 DATV for QO-100.png", "C3SCOPE-closing.png", "C3SCOPE-promo.png", "SP8ESA.png", "tescard.png")
for picture in SAMPLE_PICTURES:
    shutil.copy2(ROOT / "webapp" / "pictures" / picture, OUT / "pictures" / picture)
for document in ("docs/screenshot.png", f"docs/releases/v{version.__version__}.md", f"docs/releases/v{version.__version__}-validation.md", f"docs/releases/v{version.__version__}-components.json"):
    shutil.copy2(ROOT / document, OUT / Path(document).name)
shutil.copy2(ROOT / "LICENSE", OUT / "LICENSE")
shutil.copy2(ROOT / "LICENSE.upstream", OUT / "LICENSE-firmware-SP8ESA.txt")
(OUT / "README-PORTABLE.txt").write_text(
    f"C3CAST {version.__version__} by HB9IIU: the 5 EUR DATV modulator. Plug, flash, play.\r\n"
    "\r\n"
    "Sources and licences of everything in this package: _internal/receiver/source/SOURCES.txt, tools/ffmpeg/README.txt and H266-Player/source.\r\n"
    "1. Double-click C3CAST.exe. A window opens (close it to quit) and your browser opens the page.\r\n"
    "2. Plug the Seeed XIAO ESP32-C3 into USB. If the page does not say 'board connected', press Flash.\r\n"
    "3. Pick a picture, clock, USB camera or video, choose frequency, symbol rate and FEC, check the Level, then press Start.\r\n"
    "\r\n"
    "Your own pictures go in the 'pictures' folder (PNG or JPG, 16:9, 1280x720 is ideal).\r\n"
    "Your settings are saved in config.json next to C3CAST.exe.\r\n"
    "A screenshot of the 1.0.0 interface is included as screenshot.png.\r\n"
    "H266-Player is an optional receiver for H.265 and H.266 (its own program and licence): start it with the Player button in the page.\r\n"
    "Delete that folder if you do not need it; the button then disappears.\r\n"
    "Two integrated receiver panels are below the transmit controls. Connect a MiniTiouner, PicoTuner or RTL-SDR.\r\n"
    "Select a receiver pill, then click a signal in the spectrum to receive it. Settings controls the LNB/input or RTL gain.\r\n"
    "Receiver settings/logs live in receivers/. The receivers use the same ffmpeg as the transmitter (tools/ffmpeg).\r\n"
    "\r\n"
    "Licensed radio amateurs only. Use a filter before any amplifier and check the spectrum first.\r\n"
    "\r\n"
    "Licence: PolyForm Noncommercial 1.0.0. LICENSE covers C3CAST (HB9IIU); LICENSE-firmware-SP8ESA.txt covers the\r\n"
    "ESP32-DATV firmware by SP8ESA that C3CAST flashes to the board.\r\n"
    "ffmpeg (in the tools folder) is a GPL build: its licence, notices and where to get its source are in tools/ffmpeg/README.txt.\r\n",
    encoding="utf-8")

zip_path = shutil.make_archive(str(DIST / NAME), "zip", DIST, NAME)
checksum = hashlib.sha256(Path(zip_path).read_bytes()).hexdigest()
(DIST / f"{NAME}.sha256").write_text(f"{checksum}  {Path(zip_path).name}\n", encoding="ascii")
size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
print(f"\nbuilt {OUT}  ({size:.0f} MB)\nzip   {zip_path}  ({Path(zip_path).stat().st_size / 1e6:.0f} MB)")
