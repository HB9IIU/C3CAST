# Experimental H.266 development and validation

Local runtime updated on 29 October 2026 to GPL FFmpeg N-128187-gc49ccf40c with libvvenc. Short 640x360/30 fps
synthetic H.265/AAC and VVC/AAC MPEG-TS encodes and decodes passed; NVENC trial passed. Larger profiles and on-air
reception are still pending for production use. A subsequent 27-trial camera benchmark measured the current profiles,
alternatives and five live camera cases on an i5-11600K: see [the results](H266_BENCHMARK_2026-10-29.md).
The current high-resolution VVC profiles are too slow on that PC; no application profiles have been changed yet.
The former runtime is backed up under captures/ffmpeg-before-vvc-20261029-140426.

The console checkbox selects VVC for picture, clock or camera. It is not saved in config.json and resets to H.265 on page
load. `/api/plan` and `/api/start` accept `codec=h265|h266`; omitted means h265. The stream worker has the same `--codec`
choice. Neither the firmware nor host DVB-S2 encoder needs to understand the video codec.

## Video budget and startup

Channel capacity still comes from `dvbs2.ts_rate` (QPSK, normal frames, no pilots); TS muxrate remains 96.5% of capacity.
The unstretched video budget is `(muxrate - audio_bps - 51520) / 1.12`. VVC targets 80% of that budget and does not apply
the clock's NVENC bitrate stretch. `-maxrate` is ceil(1.5 times target), with `-bufsize` scaled from the existing formula.
The assumed 20% target overshoot fits the average budget; this is not a guarantee against bursts or TS buffer problems.
Actual streams must be measured. The command uses libvvenc, yuv420p10le, faster and period 2, without x265/NVENC options.

The existing transmitter starts with null packets and continues padding while FFmpeg warms up. No media-start deadline
has been added. Logs explain the VVC warm-up. Stop remains available while the encoder starts.

## Automated checks (no RF)

Run from the repository root:

```powershell
.venv-host/Scripts/python.exe -m unittest discover -s tests -v
.venv-host/Scripts/python.exe -m unittest discover -s host -p 'test_*.py' -v
```

The older host Qt GUI tests additionally require `host/requirements-gui.txt`; Qt is not a C3CAST runtime dependency.
New tests cover all 30 source/SR/FEC combinations, VVC options and budgets, identical audio/mux command tails, default
H.265 behavior, executable isolation, capability errors, API selection and the GUI switch/popup.

## Local executable override

From source only, `C3CAST_VVC_TEST_FFMPEG` can point to an explicitly chosen test executable. It affects VVC encoding and
its capability check only; H.265, camera enumeration and previews retain C3CAST's normal executable. The override is ignored
by the frozen app. No executable is copied or downloaded by the app.

The local `C:\mabs\h266-encoder-build\ffmpeg.exe` has nonfree/FDK-AAC enabled. It is for local tests only and must never
enter C3CAST's runtime directory, source bundle or portable package. Commands still select native AAC even during these tests.

## GPL FFmpeg handover (prepared separately)

Do not run concurrent MABS builds. Wait for the owner's current ffplay build to finish, then back up
`C:\mabs\local64\bin-video` before building. The GPL profile needs `vvenc=1` and `--enable-libvvenc`, keeping nonfree and
FDK-AAC disabled. Verify libx265, hevc_nvenc, libvvenc and native aac, and run a short VVC/AAC MPEG-TS encode.

Before packaging, retain the exact VVenC source, BSD-3-Clause-Clear licence/copyright notices, local patches if any,
FFmpeg/dependency revisions, actual configure output and checksums alongside the existing source material. Update
`docs/FFMPEG-NOTICE.txt` with those actual build details. Its current binary-specific inventory must not claim VVenC is
already supplied. The current notice records the installed build and remaining dependency inventory work. dist/ is unchanged.

## Pending media and receiver tests

The first short camera benchmark is complete; its measured alternatives are candidates for review, not accepted defaults.
Alternative FEC 4/5 profiles, long-duration motion tests, PCR analysis, receiver lip-sync and on-air validation remain pending.

With the new GPL binary, test all five symbol rates and both FECs for picture, clock and moving camera/synthetic content.
Record actual size/fps, time to first output, sustained encode speed, CPU use, video/audio rates, TS rate, continuity/PCR
errors and decoder errors. Exercise stop during warm-up and after output begins. Keep the existing source sizes/fps for
the first measurements; propose separate VVC profiles if they cannot sustain real time rather than altering H.265 profiles.

Check decode with VVC-capable ffplay and the experimental player, then arrange receiver/on-air checks separately. VLC 3
and QOCAST's normal Player are not VVC decoders. Automated command checks do not establish receiver compatibility or
real-time performance.
