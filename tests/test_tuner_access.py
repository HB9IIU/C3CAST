import ctypes as C
from contextlib import nullcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webapp'))
import receivers
import tuner_access as access


class TunerAccess(unittest.TestCase):
    def test_mini_checks_both_ports_and_closes_partial_claim(self):
        dll = Mock()
        dll.FT_OpenEx.side_effect = [0, 3]
        with patch.object(C, 'WinDLL', return_value=dll, create=True):
            with self.assertRaises(access.AccessError):
                access._mini('TEST')
        self.assertEqual(dll.FT_OpenEx.call_count, 2)
        dll.FT_Close.assert_called_once()
        serials = [C.cast(call.args[0], C.c_char_p).value for call in dll.FT_OpenEx.call_args_list]
        self.assertEqual(serials, [b'TESTA', b'TESTB'])

    def test_usb_free_busy_and_access_denied_cleanup(self):
        for opened, claimed in ((0, 0), (0, -6), (-3, 0)):
            with self.subTest(opened=opened, claimed=claimed):
                dll = Mock()
                devices = (C.c_void_p * 1)(123)
                def init(output):
                    C.cast(output, C.POINTER(C.c_void_p))[0] = 456
                    return 0
                def listing(context, output):
                    C.cast(output, C.POINTER(C.POINTER(C.c_void_p)))[0] = C.cast(devices, C.POINTER(C.c_void_p))
                    return 1
                def descriptor(device, output):
                    item = C.cast(output, C.POINTER(access.Descriptor)).contents
                    item.vendor, item.product = 0x0bda, 0x2838
                    return 0
                def opening(device, output):
                    C.cast(output, C.POINTER(C.c_void_p))[0] = 789
                    return opened
                dll.libusb_init.side_effect = init
                dll.libusb_get_device_list.side_effect = listing
                dll.libusb_get_device_descriptor.side_effect = descriptor
                dll.libusb_open.side_effect = opening
                dll.libusb_claim_interface.return_value = claimed
                with patch.object(C, 'CDLL', return_value=dll), \
                     patch.object(access.os, 'add_dll_directory', return_value=nullcontext(), create=True):
                    if opened or claimed:
                        with self.assertRaises(access.AccessError):
                            access._usb({(0x0bda, 0x2838)})
                    else:
                        self.assertTrue(access._usb({(0x0bda, 0x2838)}))
                self.assertEqual(dll.libusb_close.call_count, int(opened == 0))
                self.assertEqual(dll.libusb_release_interface.call_count, int(opened == 0 and claimed == 0))
                dll.libusb_free_device_list.assert_called_once()
                dll.libusb_exit.assert_called_once()
                dll.libusb_reset_device.assert_not_called()

    def test_refused_tuner_never_starts_worker_and_remains_connected(self):
        entry = dict(state='starting', error='')
        slot = dict(tuner='minitiouner', serial='TEST', label='MiniTiouner TEST')
        with patch.object(receivers.tuner_access, 'check', side_effect=access.AccessError(access.BUSY)), \
             patch.object(receivers.subprocess, 'Popen') as popen, \
             patch.object(receivers, '_workers', {1: entry}), \
             patch.object(receivers.tuner_assignment, 'slots', return_value=[slot]):
            receivers._launch(1, slot, entry, False)
            self.assertEqual(entry['state'], 'unavailable')
            popen.assert_not_called()
            report = receivers.status()[0]
            self.assertTrue(report['connected'])
            self.assertFalse(report['available'])
            self.assertIn('another application', report['error'])

    def test_owned_tuner_is_not_probed_again_during_status_poll(self):
        entry = dict(state='running', proc=Mock())
        entry['proc'].poll.return_value = None
        with patch.object(receivers.tuner_access, 'check') as probe, \
             patch.object(receivers, '_workers', {1: entry}), \
             patch.object(receivers.tuner_assignment, 'slots', return_value=[dict(label='Owned tuner')]):
            self.assertTrue(receivers.status()[0]['available'])
            probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
