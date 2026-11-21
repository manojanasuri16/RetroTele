"""Fake e32 for PC tests."""
import threading
import time


class Ao_lock(object):
    def __init__(self):
        self._e = threading.Event()

    def wait(self):
        self._e.wait()
        self._e.clear()

    def signal(self):
        self._e.set()


def ao_sleep(t, cb=None):
    time.sleep(t)
    if cb:
        cb()


def ao_yield():
    pass


def ao_callgate(f):
    return f


def drive_list():
    return [u'C:', u'E:']


def in_emulator():
    return 0


def start_exe(*a, **k):
    return 0


s60_version_info = (3, 2)
pys60_version = '1.4.5 final'


class Ao_timer(object):
    def __init__(self):
        self._t = None

    def after(self, sec, cb=None):
        if cb is None:
            time.sleep(sec)
            return
        self._t = threading.Timer(sec, cb)
        self._t.setDaemon(True)
        self._t.start()

    def cancel(self):
        if self._t is not None:
            self._t.cancel()
            self._t = None
