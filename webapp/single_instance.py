"""Keep separate C3CAST launches from starting competing receiver workers on Windows."""
import ctypes
import json
import os
from pathlib import Path


class MainInstance:
    def __init__(self, mutex_name='Local\\C3CAST.MainInstance'):
        self.mutex_name = mutex_name
        self.handle = None
        self.acquired = True
        self.kernel = None
        self.state_file = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'C3CAST' / 'instance.json'

    def __enter__(self):
        if os.name == 'nt':
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            self.kernel.CreateMutexW.restype = wintypes.HANDLE
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            ctypes.set_last_error(0)
            self.handle = self.kernel.CreateMutexW(None, False, self.mutex_name)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self.acquired = ctypes.get_last_error() != 183
        return self

    def publish(self, url):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({'pid': os.getpid(), 'url': url}), encoding='utf-8')

    def existing_url(self):
        try:
            value = json.loads(self.state_file.read_text(encoding='utf-8')).get('url', '')
            if value.startswith('http://127.0.0.1:') and value.removeprefix('http://127.0.0.1:').isdigit():
                return value
        except (OSError, ValueError):
            pass
        return ''

    def __exit__(self, *_):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
