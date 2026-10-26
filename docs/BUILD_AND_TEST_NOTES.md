# Build and test notes: ESP32-DATV (SP8ESA) on XIAO ESP32-C3

Upstream: https://github.com/SP8ESA/ESP32-DATV @ 915e62d (sources in `src/`, `host/`, `tools/`).

## Build (confirmed)
- `platform = platformio/espressif32@8.0.0` -> ESP-IDF 6.1.0, riscv32 gcc 15.2.0.
- Upstream says "tested with ESP-IDF 6.2.0". No such release exists (latest tag v6.1); 6.1.0 is the closest.
- Result: clean build, RAM 8.2 %, flash ~68 % of the 1 MB app slot, 4 MB flash, default single-app partition table.
- Only change to upstream firmware: `src/CMakeLists.txt` link-option line (see comment there).
  PlatformIO re-adds `-T memory.ld` after sorted LINKFLAGS, so upstream's `-Wl,-T rf_bank_guard.ld`
  became the main linker script (error: memory region 'iram_text_seg' not declared).
- PIO's SCons link also drops the CMake INTERFACE link option, so `pio_rf_guard.py`
  (`extra_scripts = post:`) re-applies the RAM-bank ASSERT to the app link only (not the bootloader).
  Margin at last check: `_heap_start` = 0x3fc9fca0, limit 0x3fca0000 (0x360 bytes).

## Flash / boot / USB (confirmed on hardware)
- Native USB Serial/JTAG, VID:PID 303A:1001. Flashed with `pio run -t upload` (esptool, hash verified).
- Firmware prints nothing at boot (log level NONE). Query `INFO` -> `ESP32DATV 1 PA_GPIO 3 CLEAN_TX 1`.

## Hardware assumptions in firmware (NOT yet verified on XIAO)
- Direct register access: Wi-Fi DAC control 0x60033D64, RF RAM bank 0x3fca0000..0x3fcc0000
  (owner reg 0x600c1020), undocumented PHY calls (`phy_set_freq`, `g_phyFuns[50]`, `rom_pbus_*`).
  These link on IDF 6.1.0, but whether they behave identically on this IDF/chip revision is untested.
- PA enable = GPIO3 (XIAO pad D1). Output only; low when idle. Leave unconnected for bench tests.
- Same silicon/USB block as upstream's SuperMini; XIAO differences are the board RF path
  (U.FL + antenna switch/matching), not the DAC. Spectral cleanliness must be measured.

## Host side (Windows)
- `.venv-host` (py 3.11): numpy, pyserial. Use CLI `host/tx_dvbs.py --port COMx`; port autodetect
  is Linux-only. The Qt GUI imports `fcntl` (Linux-only); not used.
- ffmpeg present (winget Gyan.FFmpeg). Use `--test` or `--ts` sources; camera option is V4L2 (Linux).

## QPSK rates (from `auto_sps`, computed, not measured)
| baud | sps | DAC MS/s | USB payload |
|------|-----|----------|-------------|
| 125000 | 64 | 8.000 | 31 kB/s |
| 250000 | 32 | 8.000 | 62 kB/s |
| 333000 | 24 | 7.992 | 83 kB/s |
| 500000 | 16 | 8.000 | 125 kB/s |
All use the hand-scheduled 20-cycle assembly loop at 160 MHz. Full-speed USB headroom is large.

## Loss-of-USB / stop behaviour (from source, not tested)
- RF starts only after the symbol ring is prefilled (else `ERR initial symbol buffer timed out`).
- With CLEAN_TX firmware, RF switches off when the ring drains; host must NOT send the 0xA5 0xFF stop marker.
- TX has a `seconds` limit (max 86400); `PA` pin is one-shot per TX request and forced low afterwards.
- Task and interrupt watchdogs are disabled by upstream (stream loops mask interrupts).

## First RF test (2026-10-25, HB9IIU, no PA, GPIO3 unconnected)
Command: `tx_dvbs.py --port COM4 --freq 2403.750 --baud 125000 --fec 1/2 --null --amp 100 --seconds 10`
- Firmware accepted it: 8 MS/s out, 64 sps, `PA 0`; ran ~10 s and stopped RF by itself.
- TX END: bytes_in=315188, underruns=1, late_slots=0.
- Observed on HB9IIU's ESP32 CYD pocket QO-100 spectrum viewer (receive-only, relative levels, ~2401-2410 MHz, no cable):
  a TX slot appeared at 2403.75 MHz. CONFIRMED: the Wi-Fi DAC/RF path works on the XIAO ESP32-C3.
- NOT yet verified: symbol rate, modulation quality, DAC image levels, receiver decode (needs tinySA/SDR/DATV receiver
  with attenuation). The viewer cannot show these.

## Output level vs. amp setting (reported by HB9IIU, 2026-10-25)
Measured output power for each level setting (`--amp` / web page slider; firmware accepts 1..480). Two measurement sets
were merged into one curve (set 1: amp 20..300, set 2: amp 1..480). Instrument, frequency and symbol rate were not
recorded; fill in when known. Values are as reported ("11:5" and "11:3" read as 11.5 and 11.3).
Ideal = 20 log10 amplitude, anchored at amp 23 = -10 dBm.

| amp | dBm | set | ideal dBm | diff dB |
|-----|-----|-----|-----------|---------|
| 1 | -24 | 2 | -37.2 | +13.2 |
| 15 | -13.8 | 2 | -13.7 | -0.1 |
| 20 | -11.4 | 1 | -11.2 | -0.2 |
| 23 | -10 | 2 | -10.0 | +0.0 |
| 30 | -7.5 | 1 | -7.7 | +0.2 |
| 38 | -5.8 | 2 | -5.6 | -0.2 |
| 40 | -5.6 | 1 | -5.2 | -0.4 |
| 50 | -3.5 | 1 | -3.3 | -0.2 |
| 57 | -2.38 | 2 | -2.1 | -0.3 |
| 90 | 1.17 | 1 | 1.9 | -0.7 |
| 98 | 2.3 | 2 | 2.6 | -0.3 |
| 140 | 5.15 | 1 | 5.7 | -0.5 |
| 183 | 7.52 | 2 | 8.0 | -0.5 |
| 222 | 8.8 | 1 | 9.7 | -0.9 |
| 249 | 9.74 | 2 | 10.7 | -0.9 |
| 275 | 10.8 | 1 | 11.6 | -0.8 |
| 300 | 11.5 | 1 | 12.3 | -0.8 |
| 307 | 11.3 | 2 | 12.5 | -1.2 |
| 381 | 13.35 | 2 | 14.4 | -1.0 |
| 444 | 13.9 | 2 | 15.7 | -1.8 |
| 480 | 14 | 2 | 16.4 | -2.4 |

Observations (from these numbers only):
- amp ~15..100: within ~0.3 dB of linear amplitude.
- Above ~250 the output falls increasingly below linear: -0.95 dB at 249, -1.2 at 307, -2.4 at 480 (300 -> 480 adds only ~2.7 dB).
  Compression usually means more distortion; spectral images/spurs at high levels are NOT yet measured.
- amp 1 gives -24 dBm vs -37 dBm predicted by linearity: a floor (DAC leakage/DC offset or measurement floor, cause unknown).
  Treat settings below ~15 as unreliable.
- The two sets agree within ~0.2-0.9 dB where they overlap.
- Slider range was widened to 1..480 for these measurements; decide the final range after the spectrum is measured.

## Web app (webapp/) and the QOCAST encoder strategy (2026-10-25)
Run: task "DATV: Start web app" -> http://127.0.0.1:5000 (setup page: /setup). Fixed 2405.000 MHz, DVB-S2 QPSK, no PA.
Sources: PNG picture (webapp/pictures/) or the live SBB clock card (clock_card.py, copied from HB9IIU/QOCAST;
only change: local FONT_DIR; "ESP32 DATV" line under the callsign, sized to the callsign's width).
Board discovery: saved port in webapp/config.json -> saved USB serial number -> scan of Espressif (VID 303A) ports only,
accepting a port only if it answers INFO with "ESP32DATV".

Encoding copies QOCAST (webapp/qo100_enc.py): DATV-Easy V3.08 sizes/audio per SR/FEC (640x360 at 125 kS/s ... 1920x1080
at 1000 kS/s), H.265 hevc_nvenc (p7, ll, CBR, GOP 100 at 30 fps), AAC-HE v2 via libfdk_aac, video = (mux-audio-51520)/1.12.
The clock also uses QOCAST's tested tuning (testcards/sbb_clock.qoweb.json: size/fps/video-rate stretch up to 1.3).
Pictures use the table defaults (rate 1.0) and QOCAST's test melody as audio.
Deviations (sink is the ESP, not a Pluto): mux = 96.5 % of this channel's capacity (QOCAST: exact capacity); capacity uses
normal frames without pilots; transport stream goes to tx_dvbs.py --ts - (flush_packets 1); pipeline start order: transmitter
first (null packets), then ffmpeg + frame writer. ffmpeg is QOCAST's build copied to tools/ffmpeg (FDK AAC: non-free, do not
redistribute). Needs a receiver that decodes H.265 and AAC-HE v2; GOP is 3.3 s, so a receiver may need up to that long to start.

Offline verification (files, no transmitter), 12 s each, clock and picture, SR 125/250/333/500/1000 x FEC 3/4, 4/5:
stream rate = multiplex in every case, 0 transport errors, 0 continuity errors, 0 decode errors; video 137..812 kb/s,
null packets 5..43 %. At 333+ kS/s the clock's nominal video target exceeds the multiplex (as in QOCAST); NVENC undershoots
on the static card, so the real video rate stays below it.
NOT yet verified on air: ESP chain end to end, receiver decode, clock lead time (default 5 s, from QOCAST's Pluto chain).

## USB camera source (2026-10-25)
Third source on the page ("USB camera"): DirectShow camera chosen from a list, its own microphone found by name
(webapp/camera.py pair_microphone; no match -> silent track), capture as MJPEG when the camera offers it (1280x720, or
1920x1080 for transmitted widths above 1280), same QOCAST H.265/AAC-HE v2 table as the other sources (table defaults,
no per-camera tuning). Microphone goes through QOCAST's compressor + limiter.
Overlay drawn by ffmpeg (ported from QOCAST overlays.py): callsign top left, UTC time HH:MM:SS top right, scrolling
marquee "TRANSMITTED WITH ESP32-C3 DATV" along the bottom, on dark semi-transparent bands. Seconds make the top band
change every second (QOCAST uses minutes only, to save bits).
Offline tests: overlay + encoder verified on a synthetic video; DroidCam Video, Camo and OBS Virtual Camera each produced a
valid stream (H.265 1600x900 30 fps + AAC, 717.7 kb/s multiplex, 0 transport errors, 0 decode errors); Camera (NVIDIA
Broadcast) delivered nothing (no physical camera behind it). Not yet tested: on air, and a plain USB webcam.

## Camera preview (2026-10-25)
Camera source shows a live preview before Start (640x360, 10 fps MJPEG with the overlay as transmitted). It stops when
Start is pressed (the transmission owns the camera) and the box shows "ON AIR" until the transmission ends; there is no
picture while on air. One preview at a time; closing the page or pressing Start stops its ffmpeg. The long help text under
the camera dropdown was removed. Tested with DroidCam Video: valid 640x360 JPEG frames, closing the stream frees the camera.

## PTT on D10 (2026-10-25)
Firmware change (src/main.c): PA_ENABLE_GPIO is GPIO10 (XIAO D10) instead of upstream's GPIO3 (D1). The web app always passes
--pa-enable, so D10 goes high when RF starts and low when it stops, on Stop, underrun or USB loss (upstream behaviour, other pin).
Flashed to the XIAO on COM4; INFO -> "ESP32DATV 1 PA_GPIO 10 CLEAN_TX 1", PA -> "PA GPIO 10 ARMED 0 LEVEL 0" at idle.
D10 is a plain GPIO (no strapping function; D9/GPIO9 is the BOOT button). The pin is a 3.3 V logic output: drive a relay or
amplifier enable through its own driver, with a pull-down so it stays low during reset. Verified by HB9IIU with an LED on D10: on while transmitting (2026-10-25).

## Flash from the app (2026-10-25)
webapp/flasher.py + /api/flash/*: esptool 5.6 `write-flash --erase-all` (dio, 80m, 4MB; 0x0 bootloader, 0x8000 partition table,
0x10000 app) of webapp/firmware/ (tools/export_firmware.py copies the PlatformIO build there with manifest + SHA-256).
Only Espressif USB ports can be picked; two-click confirmation on the page. Tested on the XIAO (COM4): flashed, hash verified,
answers INFO "PA_GPIO 10". COM6 (other board) was not touched. Upstream licence PolyForm Noncommercial 1.0.0: bundle includes it.

## Frequency selection and the QO-100 spectrum (2026-10-25)
webapp/static/spectrum.js is QOCAST's batc-spectrum.js without the receiver and simulator parts; webapp/bandplan.py is QOCAST's
bandplan.py unchanged. The page reads /api/bandplan (slots per symbol rate, offset 8089.5 MHz, limits, remembered frequency).
Tested in headless Edge in real time against the live feed: chip goes 'live', slot occupancy computed, a click on slot 10494.75 DN
gives 2405.250 MHz UP, at 1000 kS/s that slot is still legal, 2300.2 MHz is refused (hint + Start disabled). The BATC feed was also
read directly (101 upgrade, 922 Uint16 bins per frame). Server side: frequency validated in /api/start (check_freq), saved on start.
Audio is now native AAC-LC (see CHANGELOG 0.4.0); matrix of 40 runs (picture/clock x software/NVENC x 10 SR/FEC) clean.
