"""Audit of a built portable package: every program and library in it must have a licence and, where the licence asks for it, a
source file that really is inside the package. Writes docs/releases/v<version>-components.json and prints PASS or the list of gaps.

Usage:  python tools/package_inventory.py [path to the package folder]     (default: dist/C3CAST-Portable-x64-<version>)
"""
import fnmatch
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "webapp"))
import version  # noqa: E402

PKG = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / f"C3CAST-Portable-x64-{version.__version__}"
R, T, H, S = "_internal/receiver", "_internal/receiver/tuner-service", "H266-Player", "_internal/sources"
FFSRC = "tools/ffmpeg/source"

# (file pattern, what it is, licence, [files inside the package that carry the source], [licence texts inside the package])
# The first matching rule wins. "source" is empty only where the licence asks for no source.
RULES = [
    ("C3CAST.exe", "C3CAST (Python program packed with PyInstaller)", "PolyForm Noncommercial 1.0.0 (C3CAST), packages as listed",
     [f"{S}/PYTHON-PACKAGES.txt", f"{S}/esptool-5.6.0.tar.gz"], ["LICENSE", f"{S}/Python-PSF-LICENSE.txt"]),
    ("firmware/*.bin", "ESP32-DATV firmware by SP8ESA, as flashed to the board", "PolyForm Noncommercial 1.0.0", [], ["LICENSE-firmware-SP8ESA.txt"]),
    ("tools/ffmpeg/bin/ffmpeg.exe", "ffmpeg with x264, x265, VVenC (transmit and receive)", "GPL v2 or later",
     [f"{FFSRC}/ffmpeg-5048d707a3d57aaf91579116dbe64585a9715cd8-source.zip", f"{FFSRC}/x264-0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee-source.zip",
      f"{FFSRC}/x265-1836f70c17cde142ac023da71a96ba9cc49c9213-source.zip", f"{FFSRC}/x265-local-build.patch",
      f"{FFSRC}/vvenc-e0891287edc0d64de2d3977c4dbebff63fe367f9-source.zip", f"{FFSRC}/build_c3cast_ffmpeg_vvc.bat", f"{FFSRC}/ffmpeg-buildconf.txt"],
     ["tools/ffmpeg/licenses/COPYING.GPLv2", "tools/ffmpeg/licenses/x264-COPYING.txt", "tools/ffmpeg/licenses/x265-COPYING.txt",
      "tools/ffmpeg/licenses/VVenC-BSD-3-Clause-Clear.txt", "tools/ffmpeg/licenses/THIRD-PARTY-LICENSES.txt"]),
    (f"{R}/bin/datvrx.exe", "DATVision receiver (Rust)", "GPL v3", [f"{R}/source/DATVision-1.0.0-source.zip"], [f"{R}/licenses/DATVision-GPL.txt"]),
    (f"{R}/bin/rtl_iq.exe", "DATVision RTL-SDR reader (C++)", "GPL v3", [f"{R}/source/DATVision-1.0.0-source.zip"], [f"{R}/licenses/DATVision-GPL.txt"]),
    (f"{R}/bin/librtlsdr.dll", "rtl-sdr 2.0.2", "GPL v2 or later", [f"{R}/source/mingw-w64-rtl-sdr-2.0.2-1.src.tar.zst"], [f"{R}/licenses/librtlsdr-GPL-2.0.txt"]),
    (f"{R}/bin/libusb-1.0.dll", "libusb 1.0.28", "LGPL v2.1 or later", [f"{R}/source/mingw-w64-libusb-1.0.28-1.src.tar.zst"], [f"{R}/licenses/libusb-LGPL-2.1.txt"]),
    (f"{R}/bin/libwinpthread-1.dll", "winpthreads", "MIT and BSD-3-Clause-Clear", [], [f"{R}/licenses/libwinpthread-MIT.txt"]),
    (f"{T}/bin/tuner-service.exe", "tuner service (C#), derived from Open Tuner", "GPL v3", [f"{T}/src/Program.cs"], [f"{T}/LICENSE-GPL-3.0.txt"]),
    (f"{T}/bin/libusb-1.0.dll", "libusb 1.0.27", "LGPL v2.1 or later", [f"{R}/source/libusb-1.0.27.tar.bz2"], [f"{R}/licenses/libusb-LGPL-2.1.txt"]),
    (f"{T}/bin/LibUsbDotNet.LibUsbDotNet.dll", "LibUsbDotNet 2.2.29", "LGPL v3", [f"{R}/source/LibUsbDotNet-2.2.29-source.zip"], [f"{T}/licenses/LibUsbDotNet-LICENSE.txt"]),
    (f"{T}/bin/FTD2XX_NET.dll", "FTDI .NET wrapper", "FTDI licence (distribution allowed with its text unmodified)", [], [f"{T}/licenses/FTD2XX_NET-FTDI-licence.txt"]),
    (f"{T}/bin/Newtonsoft.Json.dll", "Json.NET 13.0.3", "MIT", [], [f"{T}/licenses/Newtonsoft.Json-MIT.txt"]),
    (f"{T}/bin/Serilog*.dll", "Serilog", "Apache 2.0", [], [f"{T}/licenses/Apache-2.0.txt"]),
    (f"{T}/bin/System.*.dll", "Microsoft .NET support library", "MIT", [], [f"{T}/THIRD-PARTY.txt"]),
    (f"{H}/HB9IIU-Experimental-H266-Player.exe", "HB9IIU Experimental H.266 Player", "GPL v3", [f"{H}/source/HB9IIU-Experimental-H266-Player-v0.2-source.zip"], [f"{H}/LICENSE-GPLv3.txt"]),
    (f"{H}/ffplay.exe", "ffplay for the player", "LGPL v2.1 or later", [f"{H}/source/ffmpeg-c0f6ae570-source.zip"], [f"{H}/FFMPEG-LICENSE.txt"]),
    (f"{H}/libusb-1.0.dll", "libusb 1.0.27", "LGPL v2.1 or later", [f"{H}/source/libusb-1.0.27.tar.bz2"], [f"{H}/licenses/libusb-LGPL-2.1.txt"]),
    (f"{H}/LibUsbDotNet.LibUsbDotNet.dll", "LibUsbDotNet 2.2.29", "LGPL v3", [f"{H}/source/LibUsbDotNet-2.2.29-source.zip"], [f"{H}/licenses/LibUsbDotNet-LICENSE.txt"]),
    (f"{H}/FTD2XX_NET.dll", "FTDI .NET wrapper", "FTDI licence", [], [f"{H}/licenses/FTD2XX_NET-FTDI-licence.txt"]),
    (f"{H}/Newtonsoft.Json.dll", "Json.NET", "MIT", [], [f"{H}/licenses/Newtonsoft.Json-MIT.txt"]),
    (f"{H}/Serilog*.dll", "Serilog", "Apache 2.0", [], [f"{H}/licenses/Apache-2.0.txt"]),
    (f"{H}/System.*.dll", "Microsoft .NET support library", "MIT", [], [f"{H}/FFMPEG-LICENSE.txt"]),
    ("videos/*.mp4", "sample film", "Creative Commons BY 3.0 (Blender Foundation)", [], ["videos/CREDITS.txt"]),
    ("_internal/*", "Python runtime and packages inside C3CAST.exe", "PSF and the packages' own licences, see PYTHON-PACKAGES.txt",
     [f"{S}/PYTHON-PACKAGES.txt"], [f"{S}/Python-PSF-LICENSE.txt"]),
]
SUFFIXES = {".exe", ".dll", ".bin", ".mp4", ".pyd"}

if not PKG.is_dir():
    sys.exit(f"package folder not found: {PKG}")
components, gaps = [], []
for path in sorted(PKG.rglob("*")):
    rel = path.relative_to(PKG).as_posix()
    if not path.is_file() or path.suffix.lower() not in SUFFIXES or "/source" in rel and rel.endswith(".zip"):
        continue
    rule = next((r for r in RULES if fnmatch.fnmatch(rel, r[0])), None)
    entry = {"path": rel, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if rule is None:
        gaps.append(f"no licence rule for {rel}")
    else:
        _, what, licence, sources, texts = rule
        entry.update(what=what, licence=licence, source=sources, licence_text=texts)
        for needed in sources + texts:
            if not (PKG / needed).exists():
                gaps.append(f"{rel}: the package lacks {needed}")
    components.append(entry)

complete = not gaps
out = ROOT / "docs" / "releases" / f"v{version.__version__}-components.json"
out.write_text(json.dumps({"version": version.__version__, "distribution_audit_complete": complete, "checked_files": len(components), "components": components},
                          indent=2) + "\n", encoding="utf-8")
print(f"{len(components)} programs and libraries checked in {PKG.name}")
print("PASS: every one has a licence and its source (or no source is required), and all those files are in the package." if complete else
      "GAPS:\n  " + "\n  ".join(sorted(set(gaps))[:40]))
sys.exit(0 if complete else 1)
