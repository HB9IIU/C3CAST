# C3CAST changelog

The version lives in `webapp/version.py` (shown on the page, the setup page and in the camera marquee).
Rules: the first public release is a beta: 1.0.0-beta.1, beta.2, ... then 1.0.0 once it has proved itself. After that a new
feature raises the middle number and a fix the last one. 0.1 to 0.4 below are the internal development versions.

## 1.0.0-beta.4
- The package includes the HB9IIU Experimental H.266 Player (folder H266-Player, GPL v3, with its source and licences). A **Player**
  button at the top of the page starts it; the button appears only while the folder is present, so it can be deleted. The
  H.266 popup now points to it instead of a web link, and is wider so it needs no scrollbar.
- Output level limits are set by the user with a **Limits** button next to the Level slider: a popup with one track and two handles
  (lowest and highest, within the firmware's 1 to 480; default 15 to 100, replacing the fixed 0 to 100), with the spike zone below
  15 and the distortion zone above 250 coloured. The slider's first step is Off, then it runs from the lowest to the highest level; the server
  checks the limits again at Start, and zero is still never sent. Levels below 15 show a spike in the middle of the signal.

- Video source: the chosen file is described in plain words (size, frame rate, codec, length, sound), with a warning when it is bigger than
  1080p or above 30 fps (your PC may stutter decoding it live), a note about black bars for a file that is not 16:9, and a note that silence
  is sent when it has no sound. An **i** button explains the best format (MP4, H.264 or H.265, 16:9, 1280x720 or smaller, 25 or 30 fps) and
  gives one command that prepares a file with the packaged ffmpeg (H.265: the package has no H.264 encoder).
- More FEC values for small dishes (asked for by OK1PHU): **1/2, 3/5 and 2/3** next to 3/4 and 4/5; 3/4 stays the default.
  A lower FEC needs less signal (about 3 dB less at 1/2 and 1.8 dB less at 3/5, compared with 3/4) and carries less video. 1/2 and 2/3
  use QOCAST's picture sizes; 3/5 has none there, so it takes the larger of the two neighbouring sizes when that still gets about
  0.011 bits per pixel, otherwise the smaller. Checked offline with the GPU and the software encoder at all five symbol rates (stream
  rate and decoding as for 3/4); not yet received on air.

## 1.0.0-beta.3
- The Video source reads a file's streams with ffmpeg itself, so the packaged app does not need ffprobe.
- Second source row with Video. The dropdown lists local videos (webapp/videos from source,
  videos next to the exe when packaged). Files loop until Stop, preserve aspect ratio and use their soundtrack or silent
  AAC when absent. Native browser preview is muted; unsupported browser formats can still be encoded by FFmpeg.
- Output slider restricted to 0–100, with transmission limited to 1–100 by the web API and media worker. Zero disables
  Start and is never passed through to the underlying transmitter's automatic (high amplitude) setting.
- Output level starts at zero and resets to zero after Stop or any transmission ending, including an error. Select a
  level again before the next transmission.
- Optional H.266 / VVC experimental switch for picture, clock and USB camera, off whenever the page opens. The information
  button explains compression, CPU load, startup delay and receiver compatibility in plain language.
- VVC uses libvvenc, 10-bit input, preset faster and period 2. Target video rate is 80% of the existing unstretched budget;
  maxrate is at least 1.5 times target. H.265 profiles, AAC audio, transport settings and radio settings are unchanged.
- A clear warning (with a warning icon) says that most DATV viewers cannot decode H.266, beside the switch and in its popup, and C3CAST asks for confirmation before it transmits in H.266.
- H.266 is refused before RF starts if FFmpeg has no libvvenc. Local runtime updated to GPL FFmpeg
  N-128187-gc49ccf40c with VVenC, without nonfree/FDK-AAC. Short H.265/AAC and VVC/AAC MPEG-TS encode/decode checks
  passed; NVENC trial passed. Exact FFmpeg, x265 and VVenC source archives retained. Portable releases are not rebuilt.
- Command and web regression tests added. An offline benchmark tool and a 27-trial C920 report cover both FECs at
  current profiles, lower-frame-rate/size alternatives and five live captures without RF. Higher-resolution VVC profiles
  are too slow on the tested i5-11600K; profile changes still need review. Long runs and on-air tuning remain pending.

## 1.0.0-beta.2
USB camera: choose the sound source (the camera's own microphone, any other Windows audio input, or silence) and adjust the
sound delay from -500 to +500 ms (plus delays the sound, minus delays the picture); both are remembered.
Experimental "Detect" button: clap in front of the camera (with a live picture and a microphone level bar) and C3CAST suggests a delay (clap test from QOCAST; it shows the camera and microphone offset only, with a possible error of about 100 ms, so fine-tune by ear and on a receiver).
Fix in the exe: the transmitter's output is no longer buffered, so the exe now starts the video instead of sending only null packets.
USB camera: a placeholder ("Starting the camera ...", or a hint when there is no picture) replaces the browser's broken-image icon.
Pictures: round arrows on the preview (and the left and right keys) replace the dropdown; the label shows the position and file name, and an "i" button explains how to add your own pictures.
Start is blocked, with a note pointing to the Setup page, while the callsign is still NOCALL (or the locator is still the placeholder).
C3CAST now ends by itself, stopping any transmission, 10 s after you close its browser page (a reload does not count), or after 3 minutes without any page request.
(C3CAST_NO_AUTOQUIT=1 turns this off.) The package ships the GPL source of its ffmpeg. Two new sample pictures (C3SCOPE).

## 1.0.0-beta.1 (first beta)
Everything of 0.1 to 0.4 below. Also: the defaults of a fresh install are callsign NOCALL and locator JNxxyy (set yours on the Setup
page; a real locator is required to save), a BETA tag in the header, brighter status text.
The console shows a welcome note (73 de HB9IIU) instead of Flask's development-server banner and its red warning, and no line per request.

## 0.4.0 (2026-10-25)
- Frequency: a live QO-100 wideband spectrum (BATC feed) in the right pane, ported from QOCAST (batc-spectrum.js and bandplan.py,
  without its receiver parts), in amber. The 14 slots of 500 kHz are green (free), red (occupied) or grey (not allowed at this symbol
  rate: all up to 333 kS/s, 9 at 500, 3 at 1000 which also needs both neighbours free); click a free slot to set the frequency
  (uplink = downlink - 8089.5 MHz).
- Frequency field: type it any time (2300 to 2450 MHz, the whole signal must fit; also offline, for bench tests). A hint says
  free / occupied / not allowed / off the slot grid. The last frequency is remembered (config.json), default 2405.000.
- Audio: native AAC-LC (the new GPL ffmpeg has no FDK): mono below 1000 kS/s, stereo at 1000; 24 kb/s at 125 kS/s.
- Software and NVENC encoding tested for picture, clock and camera (including the C920 with its microphone).

## 0.3.0 (2026-10-25)
- Flash firmware from the page: Flash button in the board row, pick an Espressif USB port, confirm twice, esptool 5.6 erases
  the board and writes the bundled firmware (webapp/firmware/, made by tools/export_firmware.py, SHA-256 checked); works on
  a blank board and updates a running one; then the board is re-checked and remembered. Never flashes on its own, refused
  while transmitting. Tested end to end on the XIAO (COM4); the blank-board case is not tested on a really blank chip.
- Licence: the upstream firmware is PolyForm Noncommercial 1.0.0 (SP8ESA): the bundle carries the licence text and the
  Required Notice; keep them with any copy you pass on, noncommercial use only.

## 0.2.0 (2026-10-25)
- Automatic encoder: hevc_nvenc on a PC with a working NVIDIA GPU, otherwise software H.265 (libx265); decided once and
  silently by a trial encode, nothing is asked. C3CAST_ENCODER=nvenc|software forces one. ffmpeg copy replaced by QOCAST's
  software-encoding build (has libx265).
- Software mode uses the plain video budget (QOCAST's 1.3 rate stretch was tuned on NVENC) and presets by size
  (ultrafast >= 1600 px, superfast >= 1280, veryfast below). On the 12-core test PC: 3.9x to 9.2x faster than real time on
  busy video; real-time runs of all SR/FEC combinations clean (0 transport, continuity and decode errors).
- PTT output: firmware change, the PA/PTT pin moved from GPIO3 (D1) to GPIO10 (D10); the app arms it on every
  transmission (--pa-enable): D10 is high while RF is on, low otherwise. Needs the reflashed firmware (INFO shows PA_GPIO 10). Verified with an LED.
- Web UI redesign: compact dark instrument-panel look, inline SVG glyphs, UTC clock, LED status chips, readout grid, header
  "by HB9IIU"; no framework and no CDN (works offline); mobile layout. Clock card keeps refreshing while on air.
- One Start/Stop toggle button; physical USB cameras listed first; camera preview before Start; provider text "C3CAST @ locator".

## 0.1.0 (2026-10-25)
First named version of the web app for the XIAO ESP32-C3 DATV transmitter (firmware: SP8ESA's ESP32-DATV).
- Fixed 2405.000 MHz, DVB-S2 QPSK; symbol rates 125/250/333/500/1000 kS/s; FEC 3/4 and 4/5; level 1..480; no PA.
- Sources: PNG picture, live SBB clock card (from QOCAST), USB camera with overlay (callsign, UTC time, marquee).
- QOCAST encoder strategy (H.265, AAC-HE v2, DATV-Easy sizes); board discovery; setup page.
- On air: the USB camera source (HD Pro Webcam C920, 500 kS/s, FEC 3/4) was received on a MiniTioune (program HB9IIU,
  1600x900, AAC audio). The clock and picture sources are not yet confirmed on air.
- Stream metadata: service name = callsign, service provider = "C3CAST @ <locator>" (what receivers such as MiniTioune show).
- Camera source: live preview before Start ("ON AIR" while transmitting); PNG/clock/camera all share the QOCAST encoder settings.
