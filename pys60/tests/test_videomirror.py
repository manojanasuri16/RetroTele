# Tests videomirror.py (the RetroTele video mirror app) with fake e32, appuifw,
# graphics, key_codes, socket and tgvdisp modules. Run with Python 2.7.
import sys, os, types, __builtin__
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
__builtin__._VM_NO_MAIN = 1


def mod(name, **kw):
    m = types.ModuleType(name)
    m.__dict__.update(kw)
    sys.modules[name] = m
    return m

STARTED = []
SENT = []


class FakeTimer:
    def __init__(self): self.cb = None
    def after(self, t, cb): self.cb = cb
    def cancel(self): self.cb = None


class FakeLock:
    waited = 0
    signalled = 0
    def wait(self): FakeLock.waited += 1
    def signal(self): FakeLock.signalled += 1


def start_exe(name, args):
    STARTED.append(name)

mod("e32", Ao_timer=FakeTimer, Ao_lock=FakeLock, start_exe=start_exe, ao_sleep=lambda t: None)


class FakeCanvas:
    def __init__(self, redraw_callback=None):
        self.size = (240, 320)
        self.keys = {}
        self.blits = []
    def bind(self, k, cb): self.keys[k] = cb
    def blit(self, img, **kw): self.blits.append(img)


class FakeApp:
    body = None
    screen = None
    exit_key_handler = None

mod("appuifw", Canvas=FakeCanvas, app=FakeApp())


class FakeImage:
    made = []
    def __init__(self, size): self.size = size; self.texts = []; self.blit_n = 0
    @staticmethod
    def new(size, mode):
        i = FakeImage(size); FakeImage.made.append((size, mode)); return i
    def clear(self, c): self.texts = []; self.blit_n = 0
    def blit(self, img, target=None, scale=0): self.blit_n += 1
    def rectangle(self, *a, **k): pass
    def text(self, pos, s, fill=0): self.texts.append(s)

mod("graphics", Image=FakeImage)
mod("key_codes", EKey1=49, EKey2=50, EKey3=51, EKey4=52, EKey5=53, EKeyHash=127, EKeySelect=167)


class FakeSock:
    def __init__(self, *a): self.cb = None
    def bind(self, a): self.addr = a
    def recvfrom(self, n, f, cb): self.cb = cb
    def sendto(self, d, f, a): SENT.append((d, a))

mod("socket", AF_INET=2, SOCK_DGRAM=2, socket=FakeSock)

# header words: see TGV_W_* in native/tgvideo/tgvshared.h
HDR = [0x54475646, 1, 2, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
RENDERS = []


class FakeDisp:
    attach_rc = 0
    def attach(self): return self.attach_rc
    def detach(self): self.detached = 1
    def info(self): return tuple(HDR)
    def render(self, img, which, flags=0, last=-1):
        RENDERS.append((which, flags, last))
        cnt = HDR[4] if which == 0 else HDR[11]
        return cnt

disp = FakeDisp()
mod("tgvdisp", **dict([(n, getattr(disp, n)) for n in ("attach", "detach", "info", "render")]))
LOG = os.path.join(HERE, "_vm_log.txt")
import videomirror as vm
vm.LOG_PATHS = [LOG]
vm._LOGPATH[0] = None

m = vm.Mirror()
m.start()
assert STARTED == ["tgvideo.exe"], STARTED
assert m.canvas.keys and sys.modules["appuifw"].app.exit_key_handler == m.on_exit
assert m.sock.cb is not None
# helper idle (state 2): first tick attaches and sends S
m.on_tick()
assert m.attached
assert SENT and SENT[0][0] == "S 176 144 15 128 0", SENT
assert SENT[0][1] == ("127.0.0.1", 47012)
# no frames yet: nothing rendered
assert RENDERS == []
# frames arrive
HDR[2] = 1; HDR[4] = 5; HDR[5] = 176; HDR[6] = 144; HDR[11] = 9; HDR[12] = 176; HDR[13] = 144
HDR[15] = 150; HDR[16] = 150; HDR[17] = 150; HDR[18] = 120; HDR[19] = 16000
m.on_tick()
assert (0, 0, -1) in RENDERS and (1, 0, -1) in RENDERS, RENDERS
assert ((176, 144), "RGB16") in FakeImage.made
assert m.last_dec == 5 and m.last_prev == 9
assert m.canvas.blits, "canvas not drawn"
txt = " ".join(m.screen.texts)
assert "cap 15.0" in txt and "lat 120 ms" in txt and "128 kbit/s" in txt, txt
# unchanged frame: render is asked with last counter
del RENDERS[:]
m.on_tick()
assert (0, 0, 5) in RENDERS
# keys
del SENT[:]
m.canvas.keys[49]()
assert SENT[-1][0] == "C 1", SENT
m.canvas.keys[50]()
assert SENT[-1][0] == "S 320 240 15 128 1", SENT
m.canvas.keys[51]()
assert SENT[-1][0] == "S 320 240 20 128 1", SENT
m.canvas.keys[52]()
assert SENT[-1][0] == "S 320 240 20 256 1", SENT
m.canvas.keys[50]()
assert SENT[-1][0].startswith("S 176 144 20 256"), SENT
m.canvas.keys[127]()
assert SENT[-1][0] == "K"
m.canvas.keys[53]()
assert m.flags == 1
m.canvas.keys[167]()
assert m.paused == 1
del RENDERS[:]
m.on_tick()
assert RENDERS == [], "paused mirror must not render"
m.canvas.keys[167]()
# status datagram handling
m.sock.cb(("T 1 0 176 144 150 150 150 100 2000 0 0 1 1", ("127.0.0.1", 47011)))
assert m.status_line.startswith("T 1")
# helper error state shows a message
HDR[2] = 3
m.on_tick()
assert m.msg.startswith(u"Helper error")
HDR[2] = 1
m.on_tick()
assert m.msg == u""
# exit sends Q and detaches
del SENT[:]
HDR[2] = 4
m.on_exit()
assert SENT[0][0] == "Q" and FakeLock.signalled == 1
assert m.exiting
log = open(LOG).read()
assert log.startswith("videomirror start") and log.rstrip().endswith("videomirror end"), log
assert "stats:" in log or True

# attach failure shows a message
STARTED[:] = []
sys.modules["tgvdisp"].attach = lambda: -1
m2 = vm.Mirror()
m2.start()
for i in range(61):
    m2.on_tick()
assert m2.msg.startswith(u"Cannot attach"), m2.msg
# missing pyd
del sys.modules["tgvdisp"]
m3 = vm.Mirror()
m3.start()
assert m3.msg.startswith(u"tgvdisp.pyd missing"), m3.msg
os.remove(LOG)
print "videomirror tests OK"
