# C3CAST redistributable FFmpeg build

Run `C:\mabs\build_c3cast_ffmpeg.bat` to configure MABS, compile, and check the resulting binary. Run from a normal command prompt. Do not run another MABS build concurrently.

Options:
- `/check`: prerequisites only, no settings changed.
- `/prepare`: write build settings without compiling.
- `/verify`: check local64/bin-video/ffmpeg.exe without building.

This profile enables GPLv3-or-later FFmpeg with libx265, NVENC, native AAC, DirectShow, and drawtext dependencies. It disables FDK-AAC and nonfree mode. GPL FFmpeg is redistributable subject to its terms; GPL does not itself prohibit commercial use. The separate SP8ESA project licence still restricts its code to noncommercial use.

Existing suite/options settings are backed up once under build/c3cast-original-*. The profile changes the shared MABS configuration and uses its existing installation prefix. Previous binaries are not automatically copied into C3CAST. It builds the current FFmpeg development source; this is not a pinned, reproducible release recipe.

IMPORTANT: C3CAST currently requests libfdk_aac and HE-AAC v2. This binary deliberately does not provide them. Before switching binaries, change the app to native `aac` with profile `aac_low`, update the displayed audio type, and retune/test audio bitrate profiles, especially at 125 kS/s. Native AAC does not encode HE-AAC v2. This script does not modify the app or replace its current FFmpeg.

## Before distributing any binary

Build configuration alone is not complete licence compliance. Provide the exact corresponding FFmpeg and linked dependency source, local patches, build scripts/configuration, copyright notices and applicable licences with your release (or a compliant source-delivery arrangement). An upstream homepage or a link to today's development branch is not matching source. Retaining the MABS build tree helps but does not automatically create a complete source package. Record commit IDs and preserve all source changes and generated build instructions before cleaning or updating MABS.

Distribute FFmpeg as a separate command-line executable called by the app. Do not apply the app's noncommercial restriction to FFmpeg. Review dependency licences and runtime DLLs as part of packaging. Passing /verify checks the forbidden flags, expected encoders and a short x265/AAC software encode; it does not validate NVENC on every GPU, camera capture, transport-stream profiles, or the entire source package.

Official references:
- https://ffmpeg.org/doxygen/trunk/md_LICENSE.html
- https://ffmpeg.org/legal.html

Prepared 25 October 2026. Full build not run as part of preparing the script.
