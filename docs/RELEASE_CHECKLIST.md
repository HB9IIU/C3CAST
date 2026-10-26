# Release checklist

Before the portable package (or a repository made public) is shared with anyone else:

- [x] ffmpeg replaced by the GPL build without FDK (x265, NVENC, native AAC); the app uses AAC-LC (done in 1.0.0-beta.1).
- [ ] **GPL obligations for that ffmpeg (and x265):** ship the matching source (or a written offer / link to exactly that source), the
      build configuration and patches, and the licence texts. `tools/ffmpeg/licenses/` still holds notices copied from the old
      package and must be reviewed against this build. Until then the portable package must not be given to anyone.
- [ ] Add `docs/screenshot.png` (the README links to it). Replace `docs/board-pic.png` with your own photo if it is Seeed's.
- [ ] Bump `webapp/version.py`, update `docs/CHANGELOG.md`.
- [ ] `python tools\export_firmware.py` (after a firmware build), then `python toolsuild_portable.py`.
- [ ] Test `C3CAST.exe` on a PC without Python and without the project folder: page, Flash, a short low-level transmission.
- [ ] Check `LICENSE` and `LICENSE-firmware-SP8ESA.txt` (the repo's `LICENSE.upstream`) are in the package (PolyForm Noncommercial: licence text and both Required Notices).
- [ ] Create the GitHub release and attach the zip.
