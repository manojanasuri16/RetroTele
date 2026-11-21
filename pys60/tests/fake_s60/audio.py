"""Fake PyS60 audio for PC tests."""
ENotReady, EOpen, EPlaying, ERecording = 0, 1, 2, 3
played = []


class Sound(object):
    @staticmethod
    def open(name):
        assert isinstance(name, unicode)
        s = Sound()
        s.name = name
        s.st = EOpen
        return s

    def play(self, times=1, interval=0, callback=None):
        played.append(self.name)
        self.st = EPlaying

    def stop(self):
        self.st = EOpen

    def close(self):
        self.st = ENotReady

    def state(self):
        return self.st

    def duration(self):
        return 185 * 1000000

    def current_position(self):
        return 42 * 1000000

    def set_position(self, p):
        pass
