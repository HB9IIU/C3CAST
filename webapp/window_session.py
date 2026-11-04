"""One controlling browser document, shared by all tabs, windows and browsers."""
import secrets
import threading
import time


class WindowLease:
    def __init__(self, ttl=180, clock=time.monotonic):
        self.ttl, self.clock = ttl, clock
        self.lock = threading.Lock()
        self.token, self.until = '', 0

    def claim(self, token):
        if not isinstance(token, str) or not 16 <= len(token) <= 128:
            return False
        with self.lock:
            now = self.clock()
            if self.token and self.until > now and not secrets.compare_digest(self.token, token):
                return False
            self.token, self.until = token, now + self.ttl
            return True

    def owns(self, token, renew=False):
        with self.lock:
            valid = bool(self.token and isinstance(token, str) and self.until > self.clock()
                         and secrets.compare_digest(self.token, token))
            if valid and renew:
                self.until = self.clock() + self.ttl
            return valid

    def release(self, token):
        with self.lock:
            if not self.token or not isinstance(token, str) or not secrets.compare_digest(self.token, token):
                return False
            self.token, self.until = '', 0
            return True

    def occupied(self):
        with self.lock:
            return bool(self.token and self.until > self.clock())
