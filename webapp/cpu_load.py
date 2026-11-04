"""Nonblocking total-system CPU sampling using Windows' cumulative CPU times."""
import ctypes
import os
import threading
import time


def system_times():
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    def ticks(value):
        return (value.dwHighDateTime << 32) | value.dwLowDateTime
    return ticks(idle), ticks(kernel) + ticks(user)  # Kernel time includes idle.


class CpuLoad:
    def __init__(self, read=system_times, clock=time.monotonic):
        self.read, self.clock = read, clock
        self.lock = threading.Lock()
        self.previous = None
        self.sampled_at = None
        self.value = None

    def percent(self):
        with self.lock:
            now = self.clock()
            if self.sampled_at is not None and now - self.sampled_at < 1:
                return self.value
            current = self.read()
            self.sampled_at = now
            self.value = None
            if current is not None and self.previous is not None:
                idle = current[0] - self.previous[0]
                total = current[1] - self.previous[1]
                if total > 0 and idle >= 0:
                    self.value = round(max(0, min(100, 100 * (total - idle) / total)))
            self.previous = current
            return self.value
