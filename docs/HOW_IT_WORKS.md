# C3CAST — How does it work?

C3CAST turns a PC and a tiny Seeed Studio XIAO ESP32-C3 board into an experimental digital amateur television (DATV) transmitter. It sends pictures and sound over radio using DVB-S2, a standard also used for satellite television.

The PC prepares the television programme. The ESP32 board creates the radio signal.

```text
Picture, live clock or USB camera + sound
                    |
                    v
       PC compresses the picture and sound
                    |
                    v
       PC adds information to repair errors
       and converts the data into symbols
                    |
                 USB cable
                    |
                    v
       ESP32 shapes and generates the radio signal
                    |
                    v
       RF output -> receiving equipment -> picture and sound
```

## 1. Choose what to transmit

You operate C3CAST through a web page running locally on your PC. Choose a still picture, an animated Swiss railway clock card, or a USB camera. The camera can use a microphone; the picture and clock sources generate their own accompanying sound.

The page also lets you choose the symbol rate, error correction and output level. Your callsign identifies the programme, and your locator identifies your station's geographical area.

## 2. The PC makes the programme small enough

Uncompressed video contains far too much data for a narrow radio channel. FFmpeg, a media-processing program, compresses the video using H.265 and the sound using AAC.

C3CAST automatically uses an NVIDIA hardware encoder when one works on the PC, or a software encoder otherwise. It chooses picture size and data rates to suit the selected radio capacity.

It then packages the video, audio and programme information into one continuous stream called an **MPEG transport stream**. Think of this as a conveyor belt carrying labelled packets of picture and sound.

## 3. The PC prepares that stream for radio

Radio signals can arrive with errors. The PC adds **forward error correction (FEC)**: extra information that helps the receiver repair damaged data without asking for it again.

It then converts the protected data into **symbols**. In the web app's QPSK mode, each symbol represents two bits by selecting one of four radio-wave phase positions. Phase describes where a wave is within its repeating cycle.

These compact symbol instructions travel to the board through its native USB connection. The PC is doing the video encoding and DVB-S2 preparation; the board does not need to process camera video itself.

## 4. The ESP32 turns symbols into radio waves

The board keeps incoming symbols in a small buffer so they can be transmitted at a steady pace.

Its firmware smooths the transitions between symbols to help keep the signal within its intended bandwidth. It generates two coordinated waveform components, called **I and Q**, and feeds them into the chip's internal Wi-Fi radio hardware.

This is the project's central trick: it uses the ESP32-C3's radio circuitry to generate a digital television signal. The transmission is DVB-S2 rather than ordinary Wi-Fi traffic. A separate external modulator is unnecessary.

The current C3CAST web app transmits at **2405.000 MHz** using **DVB-S2 QPSK**. The underlying transmitter software also includes other modes, but the web page keeps the choices simple.

## 5. A receiver reverses the process

Compatible receiving equipment recovers the symbols, corrects errors, extracts the video and audio packets, and decompresses them into a watchable programme.

The receiver needs matching frequency, DVB standard, modulation, symbol rate and FEC settings, plus support for the transmitted H.265 video and AAC audio. An ordinary Wi-Fi connection cannot receive this programme.

## What do the controls mean?

| Control | Simple explanation |
|---|---|
| Source | The picture, clock or camera you want people to see. |
| Symbol rate | How many radio symbols are sent each second. Higher rates provide more data capacity and occupy more radio bandwidth. |
| FEC | How much of the coded data carries useful information. For example, 3/4 leaves about one quarter for error correction; 4/5 leaves about one fifth. More protection reduces the capacity available for video. |
| Level | The board's signal amplitude setting. Higher settings increase output, but excessive drive can distort the signal. This is not a calibrated power reading. |
| Start / Stop | Starts or ends the transmission. |

## What happens when you press Start?

C3CAST configures the board and starts supplying radio symbols. It initially sends empty transport packets while the media encoder starts, then feeds in your selected programme.

While RF is active, **D10 (GPIO10)** goes high as a 3.3 V PTT control signal for external equipment. It is a control output, not an amplifier power supply. Stop, an exhausted symbol buffer, or the transmission time limit ends RF and returns PTT low.

## What has been demonstrated?

The project records a successful camera transmission received with MiniTioune: a Logitech C920 camera at 500 kS/s and FEC 3/4, with 1600 × 900 video and AAC audio. The D10 output was also checked with an LED. Picture and clock streams have passed offline checks; the notes do not yet confirm their reception over radio.

The board is the signal source. An eventual QO-100 station also needs the appropriate external RF chain and receiving equipment; C3CAST alone is not a complete satellite station.

---

Based on the local C3CAST 0.2.0 source, firmware and test notes reviewed on 25 October 2026. The radio-generation core comes from SP8ESA's ESP32-DATV; the media-encoding strategy and clock card were adapted from HB9IIU's QOCAST.
