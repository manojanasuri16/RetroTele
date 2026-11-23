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

HDR = [0x54475646, 1, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0] + [0] * 30
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
assert v.status_text().startswith(u"Starting video")
v.tick()                                   # helper silent: nothing sent yet
assert SENT == []
v.on_status("T hello")
v.tick()
assert SENT[-1] == ("S 176 144 15 100 1 0", ("127.0.0.1", 47012)), SENT
assert SENT[-2][0] == "L 0"                # no loopback decoder (QCIF-only, not needed)
assert v.state == cv.S_WAIT_RUN
assert ca.sent == []                       # nothing announced before the camera runs
v.on_status("T 1 1 176 144 150 150 150 12 7500 0 0 1 1")
v.tick()
assert v.state == cv.S_RUNNING
assert ("E 1", ("127.0.0.1", 47012)) in SENT and ca.sent == ["V1"], (SENT, ca.sent)
assert v.status_text() == u"Video on - front camera"
# self-view frames
assert v.frame() is None
HDR[11] = 5; HDR[12] = 176; HDR[13] = 144
v.tick()
f = v.frame()
assert f is not None and f[1:] == (176, 144) and (1, 4, -1) in RENDERS, RENDERS   # preview, mirrored (front)
n = len(CHANGES)
v.tick()                                   # same frame counter: no new redraw
assert len(CHANGES) == n
# camera switch
del SENT[:]
assert v.switch_camera() == 1 and v.cam == cv.CAM_REAR
assert SENT[-1][0] == "C 0"
assert v.status_text() == u"Video on - switching camera..."
for i in range(12):
    v.tick()
assert SENT[-1][0] == "K", SENT                        # extra IDR request after the switch
assert v.status_text() == u"Video on - rear camera"
# ---- adaptive quality: slow encoder / peer loss / drops step down to the lower rate
ca8 = callaudio_fake.CallAudio()
v8 = cv.CallVideo(ca8, None, LOG.append)
v8.start(cv.CAM_FRONT)
v8.on_status("T 2"); v8.tick()
v8.on_status("T 1 1 176 144 150 150 0 12 7500 0 0 1 0"); v8.tick()
assert v8.state == cv.S_RUNNING and v8.level == 0
GOOD = "T 1 1 176 144 150 130 0 40 20000 0 %d 1 0"
SLOW = "T 1 1 176 144 150 60 0 40 9000 0 %d 1 0"
for i in range(60):                          # warm-up is not judged
    v8.tick()
for i in range(20):
    v8.on_status(GOOD % 0)
assert v8.level == 0                         # healthy: stays
for i in range(cv.BAD_LIMIT - 1):
    v8.on_status(SLOW % 0)
assert v8.level == 0
del SENT[:]
v8.on_status(SLOW % 0)
assert v8.level == 1 and SENT[-1][0] == "S 176 144 15 56 1 0", (v8.level, SENT)
assert v8.status_text().find(u"adjusting") >= 0
for i in range(120):
    v8.tick()
assert v8.status_text() == u"Video on - front camera (low rate)", v8.status_text()
ca8.loss = 200
for i in range(30):                          # bottom of the ladder
    v8.on_status(GOOD % 0)
assert v8.level == 1
# peer loss alone steps down
v10 = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
v10.start(cv.CAM_REAR); v10.on_status("T 2"); v10.tick()
v10.on_status("T 1 0 176 144 0 0 0 0 0 0 0 1 0"); v10.tick()
for i in range(60):
    v10.tick()
v10.audio.loss = 90
for i in range(cv.BAD_LIMIT):
    v10.on_status(GOOD % 0)
assert v10.level == 1 and v10.audio.loss == 0
# many encoder drops also count
v9 = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
v9.start(cv.CAM_REAR); v9.on_status("T 2"); v9.tick()
v9.on_status("T 1 0 176 144 0 0 0 0 0 0 0 1 0"); v9.tick()
for i in range(60):
    v9.tick()
n = 0
for i in range(cv.BAD_LIMIT):
    n = n + 5
    v9.on_status(GOOD % n)
assert v9.level == 1
assert cv.parse_stats("T 1 1 320 240 150 130 0 40 20000 0 7 1 0") == (130, 20000, 7)
assert cv.parse_stats("T hello") is None
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
assert SENT[-1][0] == "S 176 144 15 100 0 0"
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

# ---- peer video: helper without camera, decoded picture, diagnostics, then our camera on top
for i in range(11, 14):
    pass
HDR[4] = 0; HDR[5] = 0; HDR[6] = 0
cax = callaudio_fake.CallAudio()
del STARTED[:], SENT[:]
del RENDERS[:]
sys.modules["tgvdisp"] = types.ModuleType("tgvdisp")
sys.modules["tgvdisp"].__dict__.update(dict([(n, getattr(disp, n)) for n in ("attach", "detach", "info", "render")]))
vr = cv.CallVideo(cax, lambda: CHANGES.append(1), LOG.append)
assert vr.start_rx() == 1 and STARTED == ["tgvideo.exe"] and vr.state == cv.S_RXSTART
assert not vr.active() and vr.helper_up() and vr.status_text() == u""
vr.tick()
assert SENT == [] and cax.sent == []
vr.on_status("T hello")
vr.tick()
assert vr.state == cv.S_RXIDLE and SENT[-1][0] == "L 0" and cax.sent[-1] == "H1" and vr.fwd_on == 1
assert vr.peer_frame() is None and vr.peer_status() == u""
HDR[28] = 1; HDR[30] = 176; HDR[31] = 320; HDR[32] = 100; HDR[33] = 13; HDR[34] = 1
vr.tick()
assert vr.peer_status().startswith(u"Peer video: starting decoder (176x320, High)"), vr.peer_status()
HDR[28] = 2; HDR[4] = 3; HDR[5] = 176; HDR[6] = 320
vr.tick()
f = vr.peer_frame()
assert f is not None and f[1:] == (176, 320) and (0, 0, -1) in RENDERS, (f, RENDERS)
assert vr.peer_status() == u"Peer video: receiving 176x320" and not vr.peer_failed()
n = len(CHANGES)
vr.tick()
assert len(CHANGES) == n                    # same frame counter: no redraw
HDR[4] = 4; HDR[5] = 528; HDR[6] = 960      # big peer picture: drawn at half size
vr.tick()
assert vr.peer_frame()[1:] == (264, 480)
HDR[28] = 4
vr.tick()
assert vr.peer_failed() and vr.peer_frame() is None
assert vr.peer_status() == u"Peer video: decoder cannot decode this stream (High profile)"
HDR[28] = 3; HDR[29] = -44
vr.tick()
assert vr.peer_status().find(u"decoder setup failed (error -44") >= 0
HDR[28] = 5; HDR[29] = -1
assert vr.peer_status() or 1
vr.tick()
HDR[28] = 2
# our camera on top of the running helper: no second exe, L 0 then S
del STARTED[:], SENT[:]
assert vr.start(cv.CAM_FRONT) == 1 and STARTED == [] and vr.state == cv.S_STARTING and vr.active()
vr.tick()
assert [d for d, a in SENT] == ["L 0", "S 176 144 15 100 1 0"], SENT
vr.on_status("T 1 1 176 144 150 150 0 12 7500 0 0 1 0")
vr.tick()
assert vr.state == cv.S_RUNNING and cax.sent[-1] == "V1"
# camera off: the helper stays for the peer's picture
del SENT[:]
vr.stop_send()
assert vr.state == cv.S_RXIDLE and [d for d, a in SENT] == ["E 0", "T"] and cax.sent[-1] == "V0"
assert not vr.active() and vr.helper_up() and vr.status_text() == u""
# camera trouble while the helper shows the peer: the helper stays, the message is kept
vr.on_status("T 2"); vr.start(cv.CAM_FRONT); vr.tick(); vr.on_status("T 3 1 0 0 0 0 0 0 0 0 0 0 0"); vr.tick()
assert vr.state == cv.S_RXIDLE and vr.status_text() == u"Camera is in use or unavailable", (vr.state, vr.status_text())
# full stop also stops the forwarding
vr.stop()
assert vr.state == cv.S_IDLE and cax.sent[-2:] == ["V0", "H0"] and vr.fwd_on == 0
# the real status path: a datagram from the helper reaches a helper that was started only for the
# peer (0.14.3 bug: the dispatcher ignored it, Python never saw the hello and gave up after 6 s)
caz = callaudio_fake.CallAudio()
vz = cv.CallVideo(caz, None, LOG.append)
del STARTED[:], SENT[:]
assert vz.start_rx() == 1 and STARTED == ["tgvideo.exe"]
cv._dispatch(("T hello 0.14.4", ("127.0.0.1", 47012)))
assert vz.hstate == 2 and vz.rx_lines == 1
vz.tick()
assert vz.state == cv.S_RXIDLE and "H1" in caz.sent
# a missed hello: the helper is pinged every 2 s, and the status line (once a second) also works
vw = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
del SENT[:]
vw.start_rx()
for i in range(21):
    vw.tick()
assert [d for d, a in SENT].count("P") == 2, SENT
cv._dispatch(("T 2 0 0 0 0 0 0 0 0 0 0 0 0", ("127.0.0.1", 47012)))
vw.tick()
assert vw.state == cv.S_RXIDLE
# our camera video after that: the running helper is reused (no second exe, no hello wait)
del STARTED[:], SENT[:]
vw.stop_send()                              # not active: nothing happens
assert vw.start(cv.CAM_FRONT) == 1 and STARTED == [] and vw.state == cv.S_STARTING
vw.tick()
assert [d for d, a in SENT][-2:] == ["L 0", "S 176 144 15 100 1 0"], SENT
# a helper that is known to be running is reused when started again
vq = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
vq.hstate = 2
del STARTED[:], SENT[:]
vq.start_rx()
assert STARTED == [] and SENT[-1][0] == "P", (STARTED, SENT)
# camera video first, peer picture added later: forwarding starts with the helper
cay = callaudio_fake.CallAudio()
vy = cv.CallVideo(cay, None, None)
vy.rx_on = 1
vy.start(cv.CAM_REAR); vy.on_status("T 2"); vy.tick()
assert "H1" in cay.sent

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
a._handle("L 77"); assert a.loss == 77
a.set_rx(1); assert sent[-1] == "W1" and a.want_rx == 1
a.set_rxfwd(1); assert sent[-1] == "H1"
del sent[:]
a._send_controls()
assert "W1" in sent and "H1" in sent    # resent when the helper starts late
a.set_video(0)
assert sent[-1] == "V0" and not a.video_active
a.want_video = 0
del sent[:]
a._send_controls()
assert "V1" not in sent                 # voice-only calls send no video control
a.stop()
assert a.peer_video == -1 and a.peer_asked == 0
print "test_callvideo OK"
