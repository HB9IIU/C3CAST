# C3CAST changelog

The version lives in `webapp/version.py` (shown on the page, the setup page and in the camera marquee).
Rules: the first public release is a beta: 1.0.0-beta.1, beta.2, ... then 1.0.0 once it has proved itself. After that a new
feature raises the middle number and a fix the last one. 0.1 to 0.4 below are the internal development versions.

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
