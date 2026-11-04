"""Which DATV receivers are plugged in? Windows device manager through ctypes (standard library only).

Recognition follows the tuner code of the QOCAST Player / OpenTuner:
  RTL-SDR       USB 0BDA:2838 or 0BDA:2832
  MiniTiouner   an FTDI chip (0403:6010) whose USB product string contains "MiniTiouner" or "NIM tuner"
  PicoTuner     a USB device whose name contains "PicoTuner" (it has no fixed ID the Player looks for)
Plugged in is not the same as free: another program may be holding the device.
"""
import ctypes as C
from ctypes import wintypes as W

SUCCESS, BUFFER_SMALL = 0, 0x1A
FILTER_ENUMERATOR, FILTER_PRESENT = 0x1, 0x100
RTL_SDR_IDS = ('VID_0BDA&PID_2838', 'VID_0BDA&PID_2832')
FTDI_ID = 'VID_0403&PID_6010'
MINITIOUNER_WORDS = ('minitiouner', 'nim tuner', 'nim db tuner')


class DevPropKey(C.Structure):
    _fields_ = [('guid', C.c_ubyte * 16), ('pid', W.DWORD)]


def _key(guid, pid):
    import uuid
    return DevPropKey((C.c_ubyte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le), pid)


KEYS = {'bus': _key('540b947e-8b40-45bc-a8a2-6a0b894cbda2', 4),       # the USB product string
        'desc': _key('a45c254e-df1c-4efd-8020-67d146a850e0', 2),      # device description
        'name': _key('b725f130-47ef-101a-a5f1-02608c4cc23e', 14)}     # friendly name


def _manager():
    cfg = C.WinDLL('cfgmgr32')
    cfg.CM_Get_Device_ID_List_SizeW.argtypes = [C.POINTER(W.ULONG), W.LPCWSTR, W.ULONG]
    cfg.CM_Get_Device_ID_ListW.argtypes = [W.LPCWSTR, C.c_wchar_p, W.ULONG, W.ULONG]
    cfg.CM_Locate_DevNodeW.argtypes = [C.POINTER(W.DWORD), W.LPCWSTR, W.ULONG]
    cfg.CM_Get_DevNode_PropertyW.argtypes = [W.DWORD, C.POINTER(DevPropKey), C.POINTER(W.ULONG), C.c_void_p,
                                             C.POINTER(W.ULONG), W.ULONG]
    return cfg


def _instance_ids(cfg):
    size = W.ULONG(0)
    if cfg.CM_Get_Device_ID_List_SizeW(C.byref(size), 'USB', FILTER_ENUMERATOR | FILTER_PRESENT) != SUCCESS:
        return []
    buffer = C.create_unicode_buffer(size.value)
    if cfg.CM_Get_Device_ID_ListW('USB', buffer, size.value, FILTER_ENUMERATOR | FILTER_PRESENT) != SUCCESS:
        return []
    return [i for i in buffer[:size.value].split('\0') if i]


def _text(cfg, instance_id, which):
    node = W.DWORD()
    if cfg.CM_Locate_DevNodeW(C.byref(node), instance_id, 0) != SUCCESS:
        return ''
    size = W.ULONG(512)
    for _ in range(2):
        buffer = C.create_string_buffer(size.value)
        kind = W.ULONG()
        result = cfg.CM_Get_DevNode_PropertyW(node, C.byref(KEYS[which]), C.byref(kind), buffer, C.byref(size), 0)
        if result == SUCCESS:
            return buffer.raw[:size.value].decode('utf-16-le', 'replace').rstrip('\0') if kind.value == 0x12 else ''
        if result != BUFFER_SMALL:
            return ''
    return ''


def detect():
    """[{'id': 'rtlsdr'|'minitiouner'|'picotuner', 'label': str, 'count': int}], in that order; [] if none."""
    try:
        cfg = _manager()
        found = {'rtlsdr': [], 'minitiouner': [], 'picotuner': []}
        for instance in _instance_ids(cfg):
            top = instance.upper()
            if any(top.startswith('USB\\' + ids + '\\') for ids in RTL_SDR_IDS):
                found['rtlsdr'].append(_text(cfg, instance, 'bus') or 'RTL-SDR')
                continue
            if top.startswith('USB\\' + FTDI_ID + '\\'):
                product = _text(cfg, instance, 'bus')
                if any(word in product.lower() for word in MINITIOUNER_WORDS):
                    found['minitiouner'].append(product)
                continue
            names = ' '.join(_text(cfg, instance, which) for which in ('bus', 'desc', 'name'))
            if 'picotuner' in names.lower():
                found['picotuner'].append('PicoTuner')
        labels = {'rtlsdr': 'RTL-SDR', 'minitiouner': 'MiniTiouner', 'picotuner': 'PicoTuner'}
        result = []
        for kind in ('rtlsdr', 'minitiouner', 'picotuner'):
            devices = found[kind]
            if not devices:
                continue
            label = labels[kind]
            if kind == 'rtlsdr' and devices[0] and devices[0] != 'RTL-SDR':
                label += ' (' + devices[0] + ')'
            # a PicoTuner shows as several USB entries (i2c and TS ports): still one tuner
            result.append({'id': kind, 'label': label, 'count': 1 if kind == 'picotuner' else len(devices)})
        return result
    except (OSError, AttributeError):
        return []                            # not Windows, or the device manager is unavailable
