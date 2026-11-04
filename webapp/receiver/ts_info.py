"""Service and stream information from the received transport stream (PAT, PMT, SDT). GPL-3.0-or-later.

The table reading follows DATVision's ui/pi_player/ts_info.py (single-packet sections; DATV tables normally
fit in one packet). Added here: aligning an arbitrary byte stream to TS packets, and the picture size read
from the video's own parameter set (H.264 / H.265 SPS, MPEG-2 sequence header), because the browser only
sees the re-encoded picture.
"""
import threading

VIDEO_TYPES = {0x01: "MPEG-1", 0x02: "MPEG-2", 0x10: "MPEG-4", 0x1B: "H.264", 0x24: "H.265", 0x33: "H.266"}
AUDIO_TYPES = {0x03: "MPEG audio", 0x04: "MPEG audio", 0x0F: "AAC", 0x11: "AAC", 0x81: "AC-3", 0x87: "E-AC-3"}
PACKET = 188
SPS_SEARCH_BYTES = 1500       # an SPS sits at the start of a keyframe's first packets


class Bits:
    """MSB-first bit reader; running out of data raises IndexError (the parameter set is incomplete)."""

    def __init__(self, data):
        self.data, self.at = data, 0

    def u(self, count):
        value = 0
        for _ in range(count):
            byte = self.at >> 3
            if byte >= len(self.data):
                raise IndexError("end of data")
            value = value << 1 | (self.data[byte] >> (7 - (self.at & 7)) & 1)
            self.at += 1
        return value

    def skip(self, count):
        if (self.at + count + 7) >> 3 > len(self.data):
            raise IndexError("end of data")
        self.at += count

    def ue(self):
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
            if zeros > 32:
                raise ValueError("bad exp-Golomb code")
        return (1 << zeros) - 1 + self.u(zeros)

    def se(self):
        value = self.ue()
        return (value + 1) // 2 if value & 1 else -(value // 2)


def unescape(nal):
    """Remove emulation prevention bytes (00 00 03 -> 00 00)."""
    out, zeros = bytearray(), 0
    for byte in nal:
        if zeros >= 2 and byte == 3:
            zeros = 0
            continue
        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(out)


def h264_size(rbsp):
    r = Bits(rbsp)
    profile = r.u(8)
    r.skip(16)                                   # constraint flags, level
    r.ue()                                       # sps id
    chroma = 1
    if profile in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
        chroma = r.ue()
        if chroma == 3:
            r.skip(1)
        r.ue(); r.ue(); r.skip(1)                # bit depths, lossless flag
        if r.u(1):                               # scaling matrices
            for index in range(8 if chroma != 3 else 12):
                if r.u(1):
                    last = nxt = 8
                    for _ in range(16 if index < 6 else 64):
                        if nxt:
                            nxt = (last + r.se() + 256) % 256
                        last = last if nxt == 0 else nxt
    r.ue()                                       # log2 max frame num
    poc = r.ue()
    if poc == 0:
        r.ue()
    elif poc == 1:
        r.skip(1); r.se(); r.se()
        for _ in range(r.ue()):
            r.se()
    r.ue(); r.skip(1)                            # reference frames, gaps allowed
    width_mbs, height_units, frame_mbs_only = r.ue() + 1, r.ue() + 1, r.u(1)
    if not frame_mbs_only:
        r.skip(1)
    r.skip(1)                                    # direct 8x8
    left = right = top = bottom = 0
    if r.u(1):
        left, right, top, bottom = r.ue(), r.ue(), r.ue(), r.ue()
    unit_x = 1 if chroma in (0, 3) else 2
    unit_y = (1 if chroma in (0, 2, 3) else 2) * (2 - frame_mbs_only)
    return width_mbs * 16 - unit_x * (left + right), (2 - frame_mbs_only) * height_units * 16 - unit_y * (top + bottom)


def h265_size(rbsp):
    r = Bits(rbsp)
    r.skip(4)                                    # vps id
    sub_layers = r.u(3)
    r.skip(1)
    r.skip(96)                                   # general profile, tier, level
    profile_present, level_present = [], []
    for _ in range(sub_layers):
        profile_present.append(r.u(1)); level_present.append(r.u(1))
    if sub_layers:
        r.skip(2 * (8 - sub_layers))
    for index in range(sub_layers):
        r.skip(88 if profile_present[index] else 0)
        r.skip(8 if level_present[index] else 0)
    r.ue()                                       # sps id
    chroma = r.ue()
    if chroma == 3:
        r.skip(1)
    width, height = r.ue(), r.ue()
    if r.u(1):                                   # conformance window
        left, right, top, bottom = r.ue(), r.ue(), r.ue(), r.ue()
        unit_x = 2 if chroma in (1, 2) else 1
        unit_y = 2 if chroma == 1 else 1
        width -= unit_x * (left + right)
        height -= unit_y * (top + bottom)
    return width, height


def picture_size(kind, data):
    """(width, height) from the first parameter set in data, None if there is none (yet)."""
    for i in range(len(data) - 4):
        if data[i] or data[i + 1] or data[i + 2] != 1:
            continue
        try:
            if kind == 0x1B and data[i + 3] & 0x1F == 7:
                return h264_size(unescape(data[i + 4:]))
            if kind == 0x24 and data[i + 3] >> 1 & 0x3F == 33:
                return h265_size(unescape(data[i + 5:]))
        except (IndexError, ValueError):
            continue                             # cut off at the end of what was collected: try again later
        if kind == 0x02 and data[i + 3] == 0xB3 and i + 7 <= len(data):
            return data[i + 4] << 4 | data[i + 5] >> 4, (data[i + 5] & 0x0F) << 8 | data[i + 6]
    return None


class TsInfo:
    """Feed it the stream as it arrives (any chunk sizes); read the snapshot from any thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.pending = b""
        self.pmt_pid = self.video_pid = self.video_kind = None
        self.service = self.provider = self.video = self.audio = ""
        self.size = None
        self.collected = b""

    def feed_stream(self, chunk):
        data = self.pending + chunk
        start = 0
        while start + PACKET <= len(data):
            # in step with the packet grid: a sync byte here and, once available, one packet later
            if data[start] != 0x47 or (start + 2 * PACKET <= len(data) and data[start + PACKET] != 0x47):
                start += 1
                continue
            self.feed(data[start:start + PACKET])
            start += PACKET
        self.pending = data[start:]

    def feed(self, data):
        for offset in range(0, len(data) - PACKET + 1, PACKET):
            if data[offset] != 0x47:
                continue
            start_flag = data[offset + 1] & 0x40
            pid = (data[offset + 1] & 0x1F) << 8 | data[offset + 2]
            control = data[offset + 3] >> 4 & 3
            start = offset + 4 + (1 + data[offset + 4] if control & 2 else 0)
            if not control & 1 or start >= offset + PACKET:
                continue
            payload = data[start:offset + PACKET]
            if pid == self.video_pid and self.size is None:
                self._video_packet(start_flag, payload)
                continue
            if not start_flag or pid not in (0, 0x11, self.pmt_pid):
                continue
            section = payload[1 + payload[0]:]
            if len(section) < 3:
                continue
            length = (section[1] & 0x0F) << 8 | section[2]
            if length < 9 or length + 3 > len(section):
                continue
            section = section[:length + 3]
            with self.lock:
                if pid == 0 and section[0] == 0x00:
                    self._pat(section)
                elif pid == 0x11 and section[0] == 0x42:
                    self._sdt(section)
                elif pid == self.pmt_pid and section[0] == 0x02:
                    self._pmt(section)

    def _video_packet(self, start_flag, payload):
        if start_flag:
            self.collected = bytes(payload)
        elif self.collected and len(self.collected) < SPS_SEARCH_BYTES:
            self.collected += bytes(payload)
        else:
            return
        size = picture_size(self.video_kind, self.collected)
        if size and size[0] > 0 and size[1] > 0:
            with self.lock:
                self.size = size

    def _pat(self, section):
        for i in range(8, len(section) - 7, 4):
            if section[i] << 8 | section[i + 1]:
                self.pmt_pid = (section[i + 2] & 0x1F) << 8 | section[i + 3]
                return

    def _pmt(self, section):
        video = audio = ""
        video_pid = video_kind = None
        i = 12 + ((section[10] & 0x0F) << 8 | section[11])
        while i + 5 <= len(section) - 4:
            kind = section[i]
            pid = (section[i + 1] & 0x1F) << 8 | section[i + 2]
            size = (section[i + 3] & 0x0F) << 8 | section[i + 4]
            if not video and kind in VIDEO_TYPES:
                video, video_pid, video_kind = VIDEO_TYPES[kind], pid, kind
            audio = audio or AUDIO_TYPES.get(kind, "") or (private_audio(section[i + 5:i + 5 + size]) if kind == 0x06 else "")
            i += 5 + size
        if video_pid != self.video_pid:
            self.size, self.collected = None, b""      # a different video stream: size unknown again
        self.video, self.audio, self.video_pid, self.video_kind = video, audio, video_pid, video_kind

    def _sdt(self, section):
        i = 11
        while i + 5 <= len(section) - 4:
            size = (section[i + 3] & 0x0F) << 8 | section[i + 4]
            j, end = i + 5, min(i + 5 + size, len(section) - 4)
            while j + 2 <= end:
                tag, body = section[j], section[j + 2:j + 2 + section[j + 1]]
                if tag == 0x48 and len(body) >= 3:
                    provider = body[2:2 + body[1]]
                    rest = body[2 + body[1]:]
                    self.provider = text(provider)
                    self.service = text(rest[1:1 + rest[0]]) if rest else ""
                    return
                j += 2 + section[j + 1]
            i += 5 + size

    def snapshot(self):
        with self.lock:
            return {'service': self.service, 'provider': self.provider, 'video': self.video, 'audio': self.audio,
                    'width': self.size[0] if self.size else None, 'height': self.size[1] if self.size else None}


def private_audio(descriptors):
    i = 0
    while i + 2 <= len(descriptors):
        tag, body = descriptors[i], descriptors[i + 2:i + 2 + descriptors[i + 1]]
        if tag == 0x6A:
            return "AC-3"
        if tag == 0x7A:
            return "E-AC-3"
        if tag == 0x05 and body[:4] == b"Opus":
            return "Opus"
        i += 2 + descriptors[i + 1]
    return ""


def text(raw):
    # DVB strings may start with a character-table selector; callsigns are plain ASCII.
    if raw and raw[0] < 0x20:
        raw = raw[3:] if raw[0] == 0x10 else raw[1:]
    return "".join(c for c in bytes(raw).decode("latin-1") if c.isprintable()).strip()
