"""Fake tgcall (native live-audio module) for PC tests."""
_state = {"on": 0, "n": 0}


def start(rate=16000, delay=500, volume=60):
    _state["on"] = 1


def stop():
    _state["on"] = 0


def stats():
    if not _state["on"]:
        return None
    _state["n"] = _state["n"] + 1
    n = _state["n"]
    return (1, 32000 * n, 31000 * n, 50 * n, 0, 0, 0, 0, 120, 640, 16000, 9000)
