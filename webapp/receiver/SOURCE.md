# Receiver source snapshot

Imported on 2026-11-04 from the local QOCAST experimental worktree:
`C:/Users/danie/Documents/AA_CODING/QOCAST-EXPERIMENTAL`.
Branch: `experimental`, HEAD: `190d1c5`.
The source included that worktree's uncommitted changes to `webplayer.py`,
`tuners.py` and `web/embed.html`; this directory preserves the actual imported code.
`webapp/tuner_assignment.py` was also adapted from the uncommitted worktree.
QOCAST itself has not been modified.
`QOCAST-WORKTREE.patch` records those four imported files' original uncommitted
changes against that HEAD, before the C3CAST adaptations.

The C# tuner service is derived from QOCAST Player / Open Tuner (GPL v3).
Full service source and existing third-party notices accompany it in `tuner-service/`.
The RTL receiver uses DATVision's `rtl_iq` and `datvrx`; see `licenses/DATVision-GPL.txt`.

C3CAST adaptations: worker dispatch, parent-pipe shutdown, dynamic ports including
PicoTuner channel 2, per-receiver sound preferences, and RX 2 muted at page load.
The tuner service binary was rebuilt from the accompanying modified C# sources.

Receive-only FFmpeg is Gyan's GPL 9.0.2 essentials build, installed separately by
`tools/prepare_receiver_ffmpeg.py`. The initial QOCAST FFmpeg binary was discarded:
it enabled nonfree/FDK and did not match the accompanying notices.
The build README now matches the installed receive binary.

Before a public release, collect and verify corresponding sources for the new
FFmpeg build and its libraries, the DATVision executables, and native dependencies.
Existing licence texts alone are not a completed redistribution-source audit.
