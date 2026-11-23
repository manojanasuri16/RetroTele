# Tests callvideo.py (send-only video helper driver) and the CallAudio video controls with
# fake e32 / socket / tgvdisp / graphics modules. Run with Python 2.7.
import sys, os, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))


def mod(name, **kw):
    m = types.ModuleType(name)
    m.__dict__.update(kw)
    sys.modules[name] = m
    return m

STARTED = []
SENT = []
SLEPT = []


class FakeTimer:
    def __init__(self): self.cb = None
    def after(self, t, cb): self.cb = cb
    def cancel(self): self.cb = None


def start_exe(name, args):
    if name == "missing.exe":
        raise IOError("no")
    STARTED.append(name)

mod("e32", Ao_timer=FakeTimer, start_exe=start_exe, ao_sleep=lambda t: SLEPT.append(t))


class FakeSock:
    def __init__(self, *a): self.cb = None
    def bind(self, a): self.addr = a
    def recvfrom(self, n, f, cb): self.cb = cb
    def sendto(self, d, f, a): SENT.append((d, a))

mod("socket", AF_INET=2, SOCK_DGRAM=2, socket=FakeSock)


class FakeImage:
    @staticmethod
    def new(size, mode):
        i = FakeImage(); i.size = size; return i

mod("graphics", Image=FakeImage)

HDR = [0x54475646, 1, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0]
RENDERS = []


class FakeDisp:
    attach_rc = 0
    def attach(self): return self.attach_rc
    def detach(self): self.detached = 1
    def info(self): return tuple(HDR)
    def render(self, img, which, flags=0, last=-1):
        RENDERS.append((which, flags, last))
        return HDR[4]

disp = FakeDisp()
mod("tgvdisp", **dict([(n, getattr(disp, n)) for n in ("attach", "detach", "info", "render")]))
sys.path.insert(0, os.path.join(HERE, "fake_s60"))
import callaudio_fake
import callvideo as cv

# ---- status parsing
assert cv.parse_status("T hello") == 2
assert cv.parse_status("T 1 1 176 144 150 150 150 12 7500 0 0 1 1") == 1
assert cv.parse_status("T 3 0 0 0 0 0 0 0 0 0 0 0 0 0") == 3
assert cv.parse_status("junk") is None and cv.parse_status("T x") is None

# ---- full start: helper idle -> S (with rotation) -> running -> E 1 + V1 -> self-view
CHANGES = []
LOG = []
ca = callaudio_fake.CallAudio()
v = cv.CallVideo(ca, lambda: CHANGES.append(1), LOG.append)
assert cv.VIDEO_ROTATION_DEG == 0
assert v.start(cv.CAM_FRONT) == 1
assert STARTED == ["tgvideo.exe"] and v.state == cv.S_STARTING
assert v.status_text().startswith(u"video starting")
v.tick()                                   # helper silent: nothing sent yet
assert SENT == []
v.on_status("T hello")
v.tick()
assert SENT[-1] == ("S 176 144 15 60 1 0", ("127.0.0.1", 47012)), SENT
assert v.state == cv.S_WAIT_RUN
assert ca.sent == []                       # nothing announced before the camera runs
v.on_status("T 1 1 176 144 150 150 150 12 7500 0 0 1 1")
v.tick()
assert v.state == cv.S_RUNNING
assert ("E 1", ("127.0.0.1", 47012)) in SENT and ca.sent == ["V1"], (SENT, ca.sent)
assert v.status_text() == u"video on, camera: front"
# self-view frames
assert v.frame() is None
HDR[4] = 5; HDR[5] = 176; HDR[6] = 144
v.tick()
f = v.frame()
assert f is not None and f[1:] == (176, 144) and (0, 0, -1) in RENDERS
n = len(CHANGES)
v.tick()                                   # same frame counter: no new redraw
assert len(CHANGES) == n
# camera switch
del SENT[:]
assert v.switch_camera() == 1 and v.cam == cv.CAM_REAR
assert SENT[-1][0] == "C 0"
assert v.status_text() == u"video on, switching camera..."
for i in range(12):
    v.tick()
assert SENT[-1][0] == "K", SENT                        # extra IDR request after the switch
assert v.status_text() == u"video on, camera: rear"
# camera error while running: video stops, helper released, call (audio) untouched
v.on_status("T 3 0 0 0 0 0 0 0 0 0 0 0 0")
v.tick()
assert v.state == cv.S_FAILED and v.msg.find(u"Camera") >= 0 and ca.sent[-1] == "V0"
assert ("Q", ("127.0.0.1", 47012)) in SENT
assert not v.active() and v.status_text() == v.msg
v.stop()                                   # stop after failure is harmless

# ---- stop: V0, E 0, Q (repeated until the helper says quitting)
ca2 = callaudio_fake.CallAudio()
v2 = cv.CallVideo(ca2, None, LOG.append)
del SENT[:]
v2.start(cv.CAM_REAR)
v2.on_status("T 2")
v2.tick()
assert SENT[-1][0] == "S 176 144 15 60 0 0"
v2.on_status("T 1 0 176 144 0 0 0 0 0 0 0 1 1")
v2.tick()
assert v2.state == cv.S_RUNNING
del SENT[:], SLEPT[:]
v2.stop()
assert v2.state == cv.S_IDLE and ca2.sent[-1] == "V0"
cmds = [d for d, a in SENT]
assert cmds[0] == "E 0" and cmds.count("Q") == 15, cmds      # helper never answered: resent, then given up
assert disp.detached
v2.stop()                                                   # idempotent
# helper confirms quitting: stops resending
v3 = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
v3.start(cv.CAM_FRONT)
v3.on_status("T 2")
v3.tick()
v3.on_status("T 1 1 176 144 0 0 0 0 0 0 0 1 1")
v3.tick()
v3.hstate = 4
del SENT[:]
v3.stop()
assert [d for d, a in SENT].count("Q") == 1

# ---- camera in use at start
ca4 = callaudio_fake.CallAudio()
v4 = cv.CallVideo(ca4, None, None)
v4.start(cv.CAM_FRONT)
v4.on_status("T 2")
v4.tick()
v4.on_status("T 3 1 0 0 0 0 0 0 0 0 0 0 0")
v4.tick()
assert v4.state == cv.S_FAILED and v4.msg == u"Camera is in use or unavailable"
assert ca4.sent == ["V0"], ca4.sent       # never announced video

# ---- helper did not start in time / missing exe
v5 = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
v5.start(cv.CAM_FRONT)
for i in range(62):
    v5.tick()
assert v5.state == cv.S_FAILED and v5.msg == u"Video helper did not start"
real_start = sys.modules["e32"].start_exe
sys.modules["e32"].start_exe = lambda n, a: (_ for _ in ()).throw(IOError("x"))
v6 = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
assert v6.start(cv.CAM_FRONT) == 0 and v6.state == cv.S_FAILED
assert v6.msg == u"Video helper tgvideo.exe is missing"
sys.modules["e32"].start_exe = real_start

# ---- no tgvdisp: video still starts, just no self-view
del sys.modules["tgvdisp"]
v7 = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
assert v7.start(cv.CAM_FRONT) == 1 and v7.tgvdisp is None
v7.on_status("T 2"); v7.tick()
v7.on_status("T 1 1 176 144 0 0 0 0 0 0 0 1 1"); v7.tick()
assert v7.state == cv.S_RUNNING and v7.frame() is None

# ---- the real CallAudio: control datagrams and helper info
import callaudio as cau
a = cau.CallAudio()
sent = []
a._sendto = lambda d: sent.append(d)
a.running = 1
a.relay = 1
a.set_video(1)
assert sent[-1] == "V1" and a.want_video == 1
a._send_controls()
assert sent[-2:] == ["R1", "M0"] or "V1" in sent[-3:], sent
a._handle("P 2"); assert a.peer_video == 2
a._handle("X 1"); assert a.peer_asked == 1
a._handle("A 1"); assert a.video_active
a.set_video(0)
assert sent[-1] == "V0" and not a.video_active
a.want_video = 0
del sent[:]
a._send_controls()
assert "V1" not in sent                 # voice-only calls send no video control
a.stop()
assert a.peer_video == -1 and a.peer_asked == 0
print "test_callvideo OK"
