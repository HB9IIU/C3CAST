"""Which receiver (web player 1, 2) gets which tuner (EXPERIMENTAL edition). Automatic: nobody chooses.

When QOCAST starts, every tuner that is plugged in is listed, in this order: the MiniTiouners (one each, by serial
number), a PicoTuner (two: channel 1 and channel 2), then the RTL-SDR. Receiver 1 takes the first, receiver 2 the
second. The list is made once and kept until QOCAST ends (a running receiver holds its tuner, which hides it from
the listing); while nothing was found yet it is made again at the next look.

Only a listing of the USB devices is read: nothing is opened.
"""

import ctypes
import sys
from ctypes import wintypes

from paths import RECEIVER as WEBPLAYER_DIR

NAMES = ("MiniTiouner", "NIM tuner")
_slots = []


class _Node(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("ID", wintypes.DWORD), ("LocId", wintypes.DWORD),
                ("SerialNumber", ctypes.c_char * 16), ("Description", ctypes.c_char * 64), ("ftHandle", ctypes.c_void_p)]


def free_tuners():
    """Serials of the MiniTiouners that show one (without the port letter: "DA582LERA" is the A port of "DA582LER"), sorted."""
    try:
        library = ctypes.WinDLL("ftd2xx.dll")
    except OSError:
        return []
    count = wintypes.DWORD(0)
    if library.FT_CreateDeviceInfoList(ctypes.byref(count)) != 0 or not count.value:
        return []
    nodes = (_Node * count.value)()
    if library.FT_GetDeviceInfoList(nodes, ctypes.byref(count)) != 0:
        return []
    found = set()
    for node in nodes[:count.value]:
        description = node.Description.decode(errors="replace")
        serial = node.SerialNumber.decode(errors="replace")
        if description.startswith(NAMES) and description.rstrip().endswith(" A") and serial:
            found.add(serial[:-1])
    return sorted(found)


def _enumerate():
    if str(WEBPLAYER_DIR) not in sys.path:
        sys.path.insert(0, str(WEBPLAYER_DIR))
    import usb_devices
    devices = usb_devices.detect()
    found = {entry["id"]: entry["count"] for entry in devices}
    result = []
    serials = next((entry.get('serials', []) for entry in devices if entry['id'] == 'minitiouner'), [])
    if len(serials) != found.get('minitiouner', 0):
        serials = free_tuners()
    for index in range(found.get("minitiouner", 0)):
        serial = serials[index] if len(serials) == found["minitiouner"] else None   # unknown ones: no pin
        result.append(dict(tuner="minitiouner", channel=1, serial=serial,
                           label="MiniTiouner" + (f" {serial}" if serial else "")))
    if "picotuner" in found:
        result += [dict(tuner="picotuner", channel=1, serial=None, label="PicoTuner channel 1"),
                   dict(tuner="picotuner", channel=2, serial=None, label="PicoTuner channel 2")]
    if "rtlsdr" in found:
        result.append(dict(tuner="rtlsdr", channel=1, serial=None, label="RTL-SDR"))
    return result


def slots():
    """[{tuner, channel, serial, label}, ...]: slot 0 is receiver 1's tuner, slot 1 receiver 2's."""
    global _slots
    if not _slots:
        try:
            _slots = _enumerate()
        except (OSError, ImportError, AttributeError):
            _slots = []
    return _slots


def slot_for(number):
    """The tuner receiver ``number`` gets, or None."""
    found = slots()
    return found[number - 1] if len(found) >= number else None
