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
DEAD = cv.DEAD_TICKS
cv.DEAD_TICKS = 1000000      # most tests tick without status lines; the watchdog is tested at the end

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
assert SENT[-1] == ("S 176 144 15 128 1 0 80", ("127.0.0.1", 47012)), SENT
assert SENT[-2][0] == "L 0"                # no loopback decoder (QCIF-only, not needed)
assert v.state == cv.S_WAIT_RUN
assert ca.sent == []                       # nothing announced before the camera runs
v.on_status("T 1 1 176 144 150 150 150 12 7500 0 0 1 1")
v.tick()
assert v.state == cv.S_RUNNING
assert ("E 1", ("127.0.0.1", 47012)) in SENT and ca.sent == ["V1"], (SENT, ca.sent)
assert v.status_text() == u"Video on - front camera"
# self-view frames (hidden by default: key 7 shows them)
assert v.frame() is None
v.toggle_self()
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
# ---- adaptive quality: down on slow encoder / drops / over budget / loss, up after clean seconds
ca8 = callaudio_fake.CallAudio()
v8 = cv.CallVideo(ca8, None, LOG.append)
v8.start(cv.CAM_FRONT)
v8.on_status("T 2"); v8.tick()
v8.on_status("T 1 1 176 144 150 150 0 12 7500 0 0 1 0"); v8.tick()
assert v8.state == cv.S_RUNNING and v8.level == 0
GOOD = "T 1 1 176 144 130 125 0 40 12000 0 %d 1 0"       # 12.5 fps, 96 kbit/s
SLOW = "T 1 1 176 144 150 60 0 40 6000 0 %d 1 0"         # encoder 9 fps behind the camera
BIG = "T 1 1 176 144 130 125 0 40 30000 0 %d 1 0"        # 240 kbit/s: over budget
for i in range(60):                                      # warm-up is not judged
    v8.tick()
for i in range(20):
    v8.on_status(GOOD % 0)
assert v8.level == 0
for i in range(cv.BAD_LIMIT - 1):
    v8.on_status(SLOW % 0)
assert v8.level == 0
del SENT[:]
v8.on_status(SLOW % 0)
assert v8.level == 1 and SENT[-1][0] == "S 176 144 15 90 1 0 65", (v8.level, SENT)
assert v8.status_text().find(u"adjusting") >= 0
for i in range(120):
    v8.tick()
assert v8.status_text() == u"Video on - front camera (reduced quality)", v8.status_text()
# a camera that is slow by itself (encoder keeps up) is not a reason to step down
for i in range(10):
    v8.on_status("T 1 1 176 144 80 80 0 40 5000 0 0 1 0")
assert v8.level == 1
# over budget steps down again, to the bottom of the ladder
del SENT[:]
for i in range(cv.BAD_LIMIT):
    v8.on_status(BIG % 0)
assert v8.level == 2 and SENT[-1][0] == "S 176 144 12 56 1 0 50", (v8.level, SENT)
for i in range(120):
    v8.tick()
v8.audio.loss = 200
for i in range(30):
    v8.on_status(GOOD % 0)
assert v8.level == 2                         # bottom of the ladder
# clean seconds step up one level; a failure soon after bans that level
v8.audio.loss = 0
del SENT[:]
for i in range(cv.UP_SECONDS):
    v8.on_status("T 1 1 176 144 130 125 0 40 5000 0 0 1 0")
assert v8.level == 1 and SENT[-1][0] == "S 176 144 15 90 1 0 65", (v8.level, SENT)
for i in range(120):
    v8.tick()
for i in range(cv.BAD_LIMIT):
    v8.on_status(BIG % 0)
assert v8.level == 2 and v8.ceiling == 2, (v8.level, v8.ceiling)
for i in range(120):
    v8.tick()
for i in range(3 * cv.UP_SECONDS):
    v8.on_status("T 1 1 176 144 130 125 0 40 5000 0 0 1 0")
assert v8.level == 2                         # never tried again
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
assert cv.parse_stats("T 1 1 320 240 150 130 0 40 20000 0 7 1 0") == (130, 20000, 7, 150)
assert cv.parse_stats("T hello") is None
# own picture: hidden by default, shown about every other tick after key 7, can be hidden again
vs = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
assert vs.show_self == 0
assert vs.toggle_self() == 1
vs.start(cv.CAM_FRONT); vs.on_status("T 2"); vs.tick()
vs.on_status("T 1 1 176 144 130 125 0 40 5000 0 0 1 0"); vs.tick()
HDR[11] = 9; HDR[12] = 176; HDR[13] = 144
del RENDERS[:]
for i in range(10):
    vs.tick()
assert 3 <= len([r for r in RENDERS if r[0] == 1]) <= 6, RENDERS      # not on every 0.2 s tick
assert vs.frame() is not None
assert vs.toggle_self() == 0 and vs.frame() is None
del RENDERS[:]
for i in range(10):
    vs.tick()
assert RENDERS == []                       # hidden: no work at all
assert vs.toggle_self() == 1
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
assert SENT[-1][0] == "S 176 144 15 128 0 0 80"
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
assert vr.peer_status() == u"Peer video 176x320" and not vr.peer_failed()
n = len(CHANGES)
vr.tick()
assert len(CHANGES) == n                    # same frame counter: no redraw
HDR[4] = 4; HDR[5] = 528; HDR[6] = 960      # big peer picture: drawn at half size
vr.tick()
assert vr.peer_frame()[1:] == (264, 480)
HDR[28] = 4                                 # too large for now: keeps receiving, no picture
vr.tick()
assert not vr.peer_failed() and vr.peer_frame() is None and vr.fwd_on == 1
assert vr.peer_status().startswith(u"Peer video too large for this phone"), vr.peer_status()
HDR[28] = 5                                 # resyncing: the last picture stays
vr.tick()
assert vr.peer_frame() is not None and vr.fwd_on == 1
HDR[28] = 3; HDR[29] = -4                   # decoder unavailable for good: receiving stops
vr.tick()
assert vr.peer_failed() and vr.peer_frame() is None
assert vr.peer_status().find(u"decoder not available (error -4") >= 0, vr.peer_status()
assert vr.fwd_on == 0 and cax.sent[-2:] == ["H0", "W0"], cax.sent[-3:]
vr.set_fwd(1)
HDR[28] = 5; HDR[29] = -1
assert vr.peer_status() or 1
vr.tick()
HDR[28] = 2
# our camera on top of the running helper: no second exe, L 0 then S
del STARTED[:], SENT[:]
assert vr.start(cv.CAM_FRONT) == 1 and STARTED == [] and vr.state == cv.S_STARTING and vr.active()
vr.tick()
assert [d for d, a in SENT] == ["L 0", "S 176 144 15 128 1 0 80"], SENT
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
assert [d for d, a in SENT][-2:] == ["L 0", "S 176 144 15 128 1 0 80"], SENT
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
a.set_agc(2); assert sent[-1] == "A2" and a.want_agc == 2
a.set_agc(7); assert sent[-1] == "A1"                  # bad value: normal
a._handle("O 2"); assert a.route_failed == 2
a._handle("B 1"); assert a.bt_links == 1
a._handle("T 5"); assert a.tel_out == 5           # tgbtroute: Bluetooth accessory active
# 0.16.1: the route goes out when the helper is ready AND again when the call is connected, even
# unchanged (the second request, after the VoIP streams started, is what makes the speaker play)
del sent[:]
a.state = "connecting"
a._set_state("connected")
assert "R%d" % a.want_route in sent, sent
a.set_route(a.want_route)
assert sent[-1] == "R%d" % a.want_route
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
# ---- watchdog: the helper dies (status lines stop) -> started again, peer picture resumes
cv.DEAD_TICKS = DEAD
cwd = callaudio_fake.CallAudio()
vd = cv.CallVideo(cwd, None, LOG.append)
del STARTED[:], SENT[:]
assert vd.start_rx() == 1 and STARTED == ["tgvideo.exe"]
vd.on_status("T hello"); vd.tick()
assert vd.state == cv.S_RXIDLE and vd.fwd_on == 1
for i in range(cv.DEAD_TICKS):
    if i % 5 == 0:
        vd.on_status("T 2 0 0 0 0 0 0 0 0 0 0 0 0")       # alive: one line a second
    vd.tick()
assert vd.state == cv.S_RXIDLE and STARTED == ["tgvideo.exe"]
for i in range(cv.DEAD_TICKS + 2):
    vd.tick()                                              # silent: presumed dead
assert STARTED == ["tgvideo.exe", "tgvideo.exe"] and vd.state == cv.S_RXSTART and vd.restarts == 1
assert vd.fwd_on == 0 and cwd.sent[-1] == "H0"
vd.on_status("T hello"); vd.tick()
assert vd.state == cv.S_RXIDLE and vd.fwd_on == 1 and cwd.sent[-1] == "H1"   # the engine asks for an IDR again
# while sending: back to the camera start
vd.start(cv.CAM_FRONT); vd.tick()
vd.on_status("T 1 1 176 144 150 150 0 12 7500 0 0 1 0"); vd.tick()
assert vd.state == cv.S_RUNNING
for i in range(cv.DEAD_TICKS + 2):
    vd.tick()
assert vd.state == cv.S_STARTING and vd.restarts == 2 and len(STARTED) == 3
vd.on_status("T hello"); vd.tick()
assert vd.state == cv.S_WAIT_RUN
vd.on_status("T 1 1 176 144 150 150 0 12 7500 0 0 1 0"); vd.tick()
assert vd.state == cv.S_RUNNING and SENT[-1][0] == "E 1"
# a helper that keeps dying: give up after HELPER_RESTARTS, the call goes on
vd.restarts = cv.HELPER_RESTARTS
for i in range(cv.DEAD_TICKS + 2):
    vd.tick()
assert vd.state == cv.S_FAILED and len(STARTED) == 3
# peer status texts (0.15.0 software decoder)
HDR[28] = 4; HDR[30] = 352; HDR[31] = 640
vq2 = cv.CallVideo(callaudio_fake.CallAudio(), None, None)
vq2.start_rx(); vq2.on_status("T hello"); vq2.tick()
vq2.inf = tuple(HDR)
assert vq2.peer_status() == u"Peer video too large for this phone (352x640), waiting for a smaller size", vq2.peer_status()
assert not vq2.peer_failed()
HDR[28] = 5
vq2.inf = tuple(HDR)
assert vq2.peer_status() == u"Peer video: decoder error, resyncing"
HDR[28] = 2
# ---- 0.15.1: pictures rendered at their shown size (tgvdisp flag 8), blitted unscaled
cfb = callaudio_fake.CallAudio()
vb = cv.CallVideo(cfb, None, LOG.append)
vb.start_rx(); vb.on_status("T hello"); vb.tick()
HDR[28] = 2; HDR[4] = 50; HDR[5] = 176; HDR[6] = 320
vb.set_peer_box((240, 280))
del RENDERS[:]
vb.tick()
f = vb.peer_frame()
assert f is not None and f[1:] == (154, 280) and RENDERS[-1][1] == 8, (f, RENDERS)
vb.set_peer_box((240, 280))                 # same box: no forced redraw
vb.set_self_box((72, 54))
assert vb.self_box == (72, 54)
# ---- both orders (0.15.1): camera first then the peer's video, peer off/on, our video off/on
cfo = callaudio_fake.CallAudio()
vo = cv.CallVideo(cfo, None, LOG.append)
del STARTED[:], SENT[:]
vo.start(cv.CAM_FRONT); vo.on_status("T hello"); vo.tick()
vo.on_status("T 1 1 176 144 150 150 0 12 7500 0 0 1 0"); vo.tick()
assert vo.state == cv.S_RUNNING and vo.fwd_on == 0 and "H1" not in cfo.sent
assert vo.start_rx() == 1 and STARTED == ["tgvideo.exe"]        # no second helper
assert vo.rx_on == 1 and vo.fwd_on == 1 and cfo.sent[-1] == "H1"
assert vo.start_rx() == 1 and cfo.sent.count("H1") == 1          # peer off/on again: nothing new
vo.stop_send()                                                   # our video off: helper stays for the peer
assert vo.state == cv.S_RXIDLE and vo.fwd_on == 1 and vo.helper_up()
vo.on_status("T 2 0 0 0 0 0 0 0 0 0 0 0 0")                       # the helper idles (camera off)
vo.start(cv.CAM_FRONT); vo.tick()                                # our video on again
assert vo.state == cv.S_WAIT_RUN, vo.state
vo.on_status("T 1 1 176 144 150 150 0 12 7500 0 0 1 0"); vo.tick()
assert vo.state == cv.S_RUNNING and vo.fwd_on == 1
# peer first, then our camera
cpf = callaudio_fake.CallAudio()
vp = cv.CallVideo(cpf, None, LOG.append)
del STARTED[:]
vp.start_rx(); vp.on_status("T hello"); vp.tick()
assert vp.state == cv.S_RXIDLE and cpf.sent[-1] == "H1"
vp.on_status("T 2 0 0 0 0 0 0 0 0 0 0 0 0")
vp.start(cv.CAM_FRONT); vp.tick()
assert vp.state == cv.S_WAIT_RUN and STARTED == ["tgvideo.exe"]
# a full stop forgets the helper: the next start launches a new one instead of "reusing" it
vp.on_status("T 1 1 176 144 150 150 0 12 7500 0 0 1 0"); vp.tick()
vp.stop()
assert vp.hstate == -1 and vp.state == cv.S_IDLE
del STARTED[:]
vp.start_rx()
assert STARTED == ["tgvideo.exe"] and vp.state == cv.S_RXSTART
print "test_callvideo OK"
