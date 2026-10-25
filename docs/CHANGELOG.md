# C3CAST changelog

The version lives in `webapp/version.py` (shown on the page, the setup page and in the camera marquee).
Rules: a new feature raises the middle number, a fix the last one.

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
