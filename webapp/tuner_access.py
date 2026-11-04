"""Brief exclusive-access probes; never reset, tune or configure USB hardware.

None means access could not be checked. The real backend open remains authoritative
because another program can acquire hardware between the probe and startup.
"""
import ctypes as C
import os

from paths import RECEIVER


BUSY = 'Receiver is in use by another application. Close that application, then click Retry.'
UNAVAILABLE = 'Receiver cannot be opened. It may be in use by another application, disconnected, or its USB driver may be unavailable. Close other receiver applications, check the USB connection, then click Retry.'


class AccessError(ValueError):
    pass


def _mini(serial):
    if not serial:
        return None
    dll = C.WinDLL('ftd2xx.dll')
    dll.FT_OpenEx.argtypes = [C.c_void_p, C.c_uint32, C.POINTER(C.c_void_p)]
    dll.FT_OpenEx.restype = C.c_uint32
    dll.FT_Close.argtypes = [C.c_void_p]
    handles = []
    try:
        for port in ('A', 'B'):
            handle = C.c_void_p()
            code = dll.FT_OpenEx(C.cast(C.c_char_p((serial + port).encode('ascii')), C.c_void_p), 1, C.byref(handle))
            if code:
                raise AccessError(UNAVAILABLE)
            handles.append(handle)
        return True
    finally:
        for handle in reversed(handles):
            dll.FT_Close(handle)


class Descriptor(C.Structure):
    _fields_ = [('length', C.c_uint8), ('kind', C.c_uint8), ('usb', C.c_uint16),
                ('device_class', C.c_uint8), ('subclass', C.c_uint8), ('protocol', C.c_uint8),
                ('packet_size', C.c_uint8), ('vendor', C.c_uint16), ('product', C.c_uint16),
                ('device', C.c_uint16), ('manufacturer', C.c_uint8), ('product_string', C.c_uint8),
                ('serial', C.c_uint8), ('configurations', C.c_uint8)]


def _usb(identities, first_only=False):
    if not identities:
        return None
    runtime = RECEIVER / 'bin'
    with os.add_dll_directory(str(runtime)):
        dll = C.CDLL(str(runtime / 'libusb-1.0.dll'))
    pointer = C.c_void_p
    signatures = {
        'libusb_init': ([C.POINTER(pointer)], C.c_int),
        'libusb_exit': ([pointer], None),
        'libusb_get_device_list': ([pointer, C.POINTER(C.POINTER(pointer))], C.c_ssize_t),
        'libusb_free_device_list': ([C.POINTER(pointer), C.c_int], None),
        'libusb_get_device_descriptor': ([pointer, C.POINTER(Descriptor)], C.c_int),
        'libusb_open': ([pointer, C.POINTER(pointer)], C.c_int),
        'libusb_close': ([pointer], None),
        'libusb_claim_interface': ([pointer, C.c_int], C.c_int),
        'libusb_release_interface': ([pointer, C.c_int], C.c_int),
    }
    for name, (args, result) in signatures.items():
        function = getattr(dll, name)
        function.argtypes, function.restype = args, result
    context, devices = pointer(), C.POINTER(pointer)()
    if dll.libusb_init(C.byref(context)):
        return None
    seen = False
    try:
        count = dll.libusb_get_device_list(context, C.byref(devices))
        if count < 0:
            return None
        for index in range(count):
            descriptor = Descriptor()
            if dll.libusb_get_device_descriptor(devices[index], C.byref(descriptor)):
                continue
            if (descriptor.vendor, descriptor.product) not in identities:
                continue
            seen = True
            handle = pointer()
            code = dll.libusb_open(devices[index], C.byref(handle))
            if code == -12:
                return None  # This driver does not support the probe; defer to the backend.
            if code:
                raise AccessError(BUSY if code == -6 else UNAVAILABLE)
            try:
                # The receiver's data/control endpoints are on interface zero.
                # Claim/release only: no reset, configuration or endpoint transfers.
                code = dll.libusb_claim_interface(handle, 0)
                if code == -12:
                    return None
                if code:
                    raise AccessError(BUSY if code == -6 else UNAVAILABLE)
                dll.libusb_release_interface(handle, 0)
            finally:
                dll.libusb_close(handle)
            if first_only:
                return True
        return True if seen else None
    finally:
        if devices:
            dll.libusb_free_device_list(devices, 1)
        dll.libusb_exit(context)


def check(slot):
    """True if the brief probe succeeds; None if unsupported; raise on refusal."""
    if os.name != 'nt':
        return None
    try:
        if slot['tuner'] == 'minitiouner':
            return _mini(slot.get('serial'))
        if slot['tuner'] == 'rtlsdr':
            return _usb({(0x0bda, 0x2838), (0x0bda, 0x2832)}, first_only=True)
        if slot['tuner'] == 'picotuner':
            return _usb({tuple(pair) for pair in slot.get('usb_ids', [])})
    except (OSError, AttributeError):
        return None  # Missing probe runtime: the real backend will report access errors.
    return None
