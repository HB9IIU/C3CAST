# C3CAST

### The 5 EUR DATV modulator

**Plug. Flash. Play.** A small web console for DVB-S2 amateur TV from a low-cost ESP32-C3 board.

<!-- screenshot: add docs/screenshot.png (the main page) -->
![C3CAST](docs/screenshot.png)

C3CAST is a simple helper around the excellent **[ESP32-DATV](https://github.com/SP8ESA/ESP32-DATV)** firmware by
**Kacper SP8ESA**. His firmware does the real work: it turns the ESP32-C3's own Wi-Fi radio into a DVB-S / DVB-S2
transmitter on 13 cm. Please read his project for how it works, its measurements and its limits; this page does not repeat them.

C3CAST only wraps it for a **Seeed Studio XIAO ESP32-C3** so that a ham can get on the air without a toolchain:

1. **Plug** the XIAO into a USB port (the native USB port, no extra adapter).
2. **Flash** it from the page: one button, two clicks, about 30 seconds. A brand-new blank board works too.
3. **Play**: pick a picture, the SBB clock card or a USB camera, choose symbol rate and FEC, press **Start**.

by HB9IIU

## The board

<img src="docs/board-pic.png" alt="Seeed Studio XIAO ESP32-C3" width="200" align="right">

The whole modulator is one **[Seeed Studio XIAO ESP32-C3](https://www.seeedstudio.com/Seeed-XIAO-ESP32C3-p-5431.html)**, a
thumb-sized board that costs about 5 EUR / USD (Seeed lists it at $4.90; shop and shipping change that).

- **Chip:** ESP32-C3, RISC-V at 160 MHz, 4 MB flash, 320 KB RAM, 2.4 GHz Wi-Fi and Bluetooth LE.
- **USB-C:** the chip's *native* USB. It is the only cable you need: the PC sends the symbols over it and C3CAST flashes through it.
- **U.FL connector** (bottom centre): the RF output. Use a small antenna, or a dummy load / attenuator for bench tests.
- **B / R buttons:** boot and reset. Flashing resets the board over USB by itself; if a board is ever not found, hold **B** while
  plugging it in to force download mode.
- **Pin D10:** the PTT output of C3CAST (high while transmitting). D9 is the boot button: do not pull it low at power-up.

The RF is produced by the chip's own Wi-Fi radio, driven by SP8ESA's firmware; there is no other RF hardware on the board. C3CAST is
built and tested on this XIAO. SP8ESA's own project uses an ESP32-C3 SuperMini.

## What you get

- **Flash button**: installs the firmware (SP8ESA's, with the PTT pin moved to D10) over the same USB cable. It only flashes the
  board you pick and confirm. No Arduino IDE, no PlatformIO needed to use it.
- **Three sources**: a PNG/JPG picture, a live **SBB station-clock test card**, or a **USB camera** with callsign, UTC time and a
  scrolling marquee on the picture.
- **Link settings**: 2405.000 MHz, DVB-S2 QPSK, symbol rates 125 / 250 / 333 / 500 / 1000 kS/s, FEC 3/4 or 4/5, output level 1 to 480.
- **Sensible video settings automatically**: picture size, bitrate and audio follow the symbol rate (H.265 and HE-AAC, the same
  strategy as QOCAST). It uses the NVIDIA GPU encoder when there is one, otherwise software encoding. Nothing to configure.
- **PTT output on D10**: high while RF is on, low otherwise; to key a relay or an amplifier through its own driver.
- **Finds the board by itself** (and remembers it), shows UTC, runs offline (no internet needed), one Start/Stop button.

## Quick start (Windows)

You need: a XIAO ESP32-C3, a USB cable, Windows, Python 3.11, and an ffmpeg build with `libfdk_aac` (see *Notes* below).

```
py -3.11 -m venv .venv-host
.venv-host\Scripts\pip install -r webapp\requirements.txt
.venv-host\Scripts\python webapp\app.py
```

Open <http://127.0.0.1:5000>. In VS Code the task **DATV: Start web app** does the same. The page then says *board connected*;
if it does not, use **Flash**. Set your callsign, locator and clock lead time on the **Setup** page.

## Please read before transmitting

- **Licensed radio amateurs only.** You are responsible for the frequency, power and bandwidth you use.
- The signal comes from the chip's DAC, so unwanted **images** are present (SP8ESA shows them in his plots). Use a proper
  **filter** before any amplifier, and check the spectrum on a bench first. Start with a dummy load or attenuator.
- C3CAST is made for experiments, not for calibrated power: see *Output level* in `docs/BUILD_AND_TEST_NOTES.md`.

## Status

Version **0.3.0**. Verified on air so far: DVB-S2 QPSK at 500 kS/s with the USB camera source, received on a MiniTioune. The other
symbol rates, FEC values and sources are checked offline (streams analysed without errors) but not all confirmed on air yet.
The firmware comes from the SP8ESA project, so its limits apply: see his page for compatibility details.

## Notes

- **ffmpeg** is not included: the build used here (H.265 NVENC/x265 plus FDK AAC) cannot be redistributed. Put an ffmpeg with those
  encoders in `tools/ffmpeg/bin/` (QOCAST ships a suitable one).
- **Camera** support uses Windows DirectShow; other systems are not supported yet.
- **Firmware source** is in `src/` (PlatformIO, ESP-IDF 6.1). To rebuild it: `pio run`, then `python tools/export_firmware.py`
  to refresh what the Flash button writes.
- More details in `docs/CHANGELOG.md` and `docs/BUILD_AND_TEST_NOTES.md`.

## Credits and licence

- **ESP32-DATV firmware: Kacper SP8ESA** (<https://github.com/SP8ESA/ESP32-DATV>). All the clever part is his work.
- **QOCAST by HB9IIU**: the SBB clock card and the encoder settings (which come from DATV-Easy's automatic mode).

**Licence: PolyForm Noncommercial 1.0.0, the same as the firmware** (see `LICENSE`). Free for noncommercial use, which the licence
explicitly says includes hobby projects and amateur pursuits. Anyone you pass a copy to must get the licence text and the
*Required Notice* lines at the top of `LICENSE` (HB9IIU for C3CAST, SP8ESA for the firmware). No commercial use.

Third-party parts keep their own licences: the Varela Round font (SIL OFL, in `webapp/fonts/`), esptool and the other Python
packages (installed by pip, not part of this repository), ffmpeg (not included).

73 de HB9IIU
