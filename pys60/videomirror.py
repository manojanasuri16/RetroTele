# RetroTele video mirror (installed as default.py of RetroTele-videomirror.sis).
# STAGE 1 of video calls: camera -> H.264 encoder -> H.264 decoder -> screen, all
# on this phone. The codecs run in the helper tgvideo.exe (it has MultimediaDD);
# frames come back through the global chunk "tgvideo_frames", which tgvdisp.pyd
# converts into graphics.Image objects. Commands go to the helper over UDP
# 127.0.0.1:47012, its status lines arrive on 127.0.0.1:47011.
# Python 2.2 compatible. e32socket rule: sockets are never close()d while the
# app runs (see retrotele.py PhoneConn).
#
# Default pipeline: camera + encoder running, then hardware decoder uid 0x102073ef (loopback).
# Keys: 1 rear/front camera, 2 size 176x144 <-> 320x240, 3 fps 10/15/20,
#       4 bitrate 64/128/256, # keyframe, centre pause/resume,
#       6 decoder order sweep (diagnostic, still available, about 1 minute, also started once automatically
#       when the decoder is blocked), 5 colour flags (debug: swap U/V, swap 4:2:2 byte order), Back = exit.
import sys
import os
import types
import socket
import e32
import appuifw
import graphics
import key_codes

HOST = "127.0.0.1"
PORT_CMD = 47012        # helper listens here
PORT_STATUS = 47011     # we listen here
LOG_PATHS = ["E:\\retrotele_videomirror.txt", "C:\\Data\\retrotele_videomirror.txt"]
TICK = 0.07
MIRROR_VERSION = "0.13.3 loopback camera+encoder+decoder 0x102073ef"

SIZES = [(176, 144), (320, 240)]
FPSES = [10, 15, 20]
RATES = [64, 128, 256]
CAMS = [u"rear", u"front"]

# header words of tgvdisp.info() (same order as TGV_W_* in native/tgvideo/tgvshared.h)
I_STATE = 2
I_DEC_COUNT = 4
I_DEC_W = 5
I_DEC_H = 6
I_DEC_PATTERN = 7
I_DEC_LAYOUT = 8
I_PREV_COUNT = 11
I_PREV_W = 12
I_PREV_H = 13
I_CAM = 14
I_CAP_FPS = 15
I_ENC_FPS = 16
I_DEC_FPS = 17
I_LAT = 18
I_BPS = 19
I_ERRORS = 20
I_DROPS = 21
I_ENC_OK = 22
I_DEC_OK = 23
I_ORDER = 25
I_BLOCKED = 26
I_SWEEP = 27
S_SWEEPING = 5

_LOGPATH = [None]


def log(msg):
    # one open per line: the helper appends to the same file
    paths = LOG_PATHS
    if _LOGPATH[0] is not None:
        paths = [_LOGPATH[0]]
    for p in paths:
        try:
            f = open(p, "a")
            f.write(msg + "\n")
            f.close()
            _LOGPATH[0] = p
            return
        except:
            pass


def _raw(sock):
    return getattr(sock, "_sock", sock)


def _is_err(res):
    return (type(res) is types.TupleType and len(res) == 2 and
            type(res[0]) in (types.ClassType, types.TypeType))


def _fresh_log():
    for p in LOG_PATHS:
        try:
            os.remove(p)
        except:
            pass


class Mirror:
    def __init__(self):
        self.tgvdisp = None
        self.msg = u""
        self.attached = 0
        self.helper_started = 0
        self.sent_s = 0
        self.sent_s_tick = 0
        self.paused = 0
        self.exiting = 0
        self.tick_no = 0
        self.size_i = 0
        self.fps_i = 1
        self.rate_i = 1
        self.cam = 0
        self.flags = 0
        self.last_dec = -1
        self.last_prev = -1
        self.img_dec = None
        self.img_prev = None
        self.dec_size = (0, 0)
        self.prev_size = (0, 0)
        self.dirty = 1
        self.info = None
        self.status_line = ""
        self.rx = 0
        self.sock = None
        self.pending = 0
        self.timer = e32.Ao_timer()
        self.lock = e32.Ao_lock()
        self.canvas = None
        self.screen = None
        self.auto_d = 0
        self.dec_rc = 0
        self.prev_rc = 0

    # ---------------------------------------------------------- start / stop
    def start(self):
        _fresh_log()
        log("videomirror start " + MIRROR_VERSION)
        try:
            import tgvdisp
            self.tgvdisp = tgvdisp
        except:
            self.fail(u"tgvdisp.pyd missing or cannot load", "import tgvdisp")
        self.canvas = appuifw.Canvas(redraw_callback=self.redraw)
        appuifw.app.body = self.canvas
        try:
            appuifw.app.screen = "full"
        except:
            pass
        appuifw.app.exit_key_handler = self.on_exit
        self.bind_keys()
        w, h = self.canvas.size
        self.screen = graphics.Image.new((w, h), 'RGB16')
        self.open_socket()
        if self.tgvdisp is not None:
            self.start_helper()
        self.timer.after(TICK, self.on_tick)

    def fail(self, text, detail):
        self.msg = text
        self.dirty = 1
        log("ERROR: " + str(detail) + " / " + str(sys.exc_info()[1]))

    def open_socket(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((HOST, PORT_STATUS))
            self.sock = s
            self.arm()
        except:
            self.sock = None
            self.fail(u"cannot open UDP port 47011", "bind")

    def arm(self):
        if self.sock is None or self.pending or self.exiting:
            return
        self.pending = 1
        try:
            _raw(self.sock).recvfrom(512, 0, self.on_status)
        except:
            self.pending = 0
            log("recvfrom failed: " + str(sys.exc_info()[1]))

    def on_status(self, res):
        self.pending = 0
        data = None
        if _is_err(res):
            pass
        elif type(res) is types.TupleType and len(res) == 2:
            data = res[0]
        elif type(res) is types.StringType:
            data = res
        self.arm()
        if data:
            self.rx = self.rx + 1
            self.status_line = data
            if data[:1] == "T" and self.rx <= 3:
                log("helper status: " + data)

    def send(self, data):
        if self.sock is None:
            return 0
        try:
            _raw(self.sock).sendto(data, 0, (HOST, PORT_CMD))
            return 1
        except:
            log("sendto failed: " + str(sys.exc_info()[1]))
            return 0

    def start_helper(self):
        log("starting tgvideo.exe")
        try:
            e32.start_exe(u"tgvideo.exe", u"")
            self.helper_started = 1
        except:
            self.fail(u"Helper tgvideo.exe is missing", "start_exe")

    def try_attach(self):
        if self.attached or self.tgvdisp is None or not self.helper_started:
            return
        try:
            rc = self.tgvdisp.attach()
        except:
            rc = -1
            log("attach raised: " + str(sys.exc_info()[1]))
        if rc == 0:
            self.attached = 1
            self.msg = u""
            log("chunk attached")
        elif self.tick_no == 60 or (self.tick_no > 60 and self.tick_no % 140 == 0):
            self.fail(u"Cannot attach video chunk (%s)" % str(rc), "attach rc=" + str(rc))

    def params(self):
        sz = SIZES[self.size_i]
        return "S %d %d %d %d %d" % (sz[0], sz[1], FPSES[self.fps_i], RATES[self.rate_i], self.cam)

    def send_start(self):
        cmd = self.params()
        log("send: " + cmd)
        if self.send(cmd):
            self.sent_s = 1
            self.sent_s_tick = self.tick_no

    # ---------------------------------------------------------- keys
    def bind_keys(self):
        c = self.canvas
        c.bind(key_codes.EKey1, self.key_cam)
        c.bind(key_codes.EKey2, self.key_size)
        c.bind(key_codes.EKey3, self.key_fps)
        c.bind(key_codes.EKey4, self.key_rate)
        c.bind(key_codes.EKey5, self.key_flags)
        c.bind(key_codes.EKey6, self.key_sweep)
        c.bind(key_codes.EKeyHash, self.key_keyframe)
        c.bind(key_codes.EKeySelect, self.key_pause)

    def key_cam(self):
        self.cam = 1 - self.cam
        log("key: camera -> %d" % self.cam)
        self.send("C %d" % self.cam)
        self.dirty = 1

    def key_size(self):
        self.size_i = (self.size_i + 1) % len(SIZES)
        self.restart("size")

    def key_fps(self):
        self.fps_i = (self.fps_i + 1) % len(FPSES)
        self.restart("fps")

    def key_rate(self):
        self.rate_i = (self.rate_i + 1) % len(RATES)
        self.restart("bitrate")

    def restart(self, what):
        log("key: " + what)
        self.last_dec = -1
        self.last_prev = -1
        if self.sent_s:
            self.send_start()
        self.dirty = 1

    def key_flags(self):
        self.flags = (self.flags + 1) % 4
        log("key: render flags -> %d" % self.flags)
        self.last_dec = -1
        self.dirty = 1

    def key_sweep(self):
        log("key: order sweep (D)")
        self.send("D")
        self.dirty = 1

    def key_keyframe(self):
        log("key: keyframe")
        self.send("K")

    def key_pause(self):
        self.paused = 1 - self.paused
        log("key: paused=%d" % self.paused)
        self.dirty = 1

    # ---------------------------------------------------------- exit
    def on_exit(self):
        if self.exiting:
            return
        self.exiting = 1
        log("exit requested")
        self.send("Q")
        n = 0
        while n < 20:
            e32.ao_sleep(0.1)
            n = n + 1
            st = None
            if self.attached:
                try:
                    inf = self.tgvdisp.info()
                    if inf is not None:
                        st = inf[I_STATE]
                except:
                    pass
            if st == 4:
                break
        log("helper state after Q: " + str(st) + " (waited %d ms)" % (n * 100))
        if self.attached:
            try:
                self.tgvdisp.detach()
            except:
                pass
        log("videomirror end")
        appuifw.app.exit_key_handler = None
        self.lock.signal()

    # ---------------------------------------------------------- timer
    def on_tick(self):
        if self.exiting:
            return
        self.tick_no = self.tick_no + 1
        self.timer.after(TICK, self.on_tick)
        try:
            self.step()
        except:
            log("tick error: " + str(sys.exc_info()[1]))
            self.msg = u"Internal error, see log"
            self.dirty = 1

    def step(self):
        self.try_attach()
        if not self.attached:
            if self.tick_no % 14 == 1:
                self.dirty = 1
            self.redraw_if_needed()
            return
        inf = None
        try:
            inf = self.tgvdisp.info()
        except:
            pass
        self.info = inf
        if inf is None:
            self.redraw_if_needed()
            return
        st = inf[I_STATE]
        # the helper listens once its state is 2 (idle): send S then (and again if it stays idle)
        if st == 2 and (not self.sent_s or self.tick_no - self.sent_s_tick > 140):
            self.send_start()
        if len(inf) > I_SWEEP and inf[I_BLOCKED] == 1 and inf[I_SWEEP] == 0 and not self.auto_d:
            self.auto_d = 1
            log("decoder blocked (-44): starting the order sweep once")
            self.send("D")
        if st == S_SWEEPING:
            self.msg = u"Diagnostic sweep running (about 1 min)..."
        elif st == 3:
            self.msg = u"Helper error: camera/codec failed (see log)"
        elif len(inf) > I_SWEEP and inf[I_BLOCKED] == 1 and inf[I_SWEEP] == 2:
            self.msg = u"decoder blocked while camera runs"
        elif self.msg[:6] == u"Helper" or self.msg[:10] == u"Diagnostic" or self.msg[:7] == u"decoder":
            self.msg = u""
        if not self.paused:
            self.draw_frames(inf)
        if self.tick_no % 14 == 0:
            self.log_stats(inf)
            self.dirty = 1
        self.redraw_if_needed()

    def make_image(self, old, oldsize, w, h):
        if old is not None and oldsize == (w, h):
            return old, oldsize
        if w <= 0 or h <= 0:
            return old, oldsize
        log("new image %dx%d" % (w, h))
        return graphics.Image.new((w, h), 'RGB16'), (w, h)

    def draw_frames(self, inf):
        if inf[I_DEC_COUNT] > 0:
            self.img_dec, self.dec_size = self.make_image(self.img_dec, self.dec_size, inf[I_DEC_W], inf[I_DEC_H])
            if self.img_dec is not None:
                rc = self.tgvdisp.render(self.img_dec, 0, self.flags, self.last_dec)
                if rc >= 0:
                    if rc != self.last_dec:
                        self.dirty = 1
                    self.last_dec = rc
                if rc != self.dec_rc and rc < 0:
                    log("render decoded rc=%d" % rc)
                self.dec_rc = rc
        if inf[I_PREV_COUNT] > 0:
            self.img_prev, self.prev_size = self.make_image(self.img_prev, self.prev_size, inf[I_PREV_W], inf[I_PREV_H])
            if self.img_prev is not None:
                rc = self.tgvdisp.render(self.img_prev, 1, 0, self.last_prev)
                if rc >= 0:
                    if rc != self.last_prev:
                        self.dirty = 1
                    self.last_prev = rc
                if rc != self.prev_rc and rc < 0:
                    log("render preview rc=%d" % rc)
                self.prev_rc = rc

    def stats_lines(self, inf):
        lines = []
        lines.append(u"cap %d.%d enc %d.%d dec %d.%d fps" % (inf[I_CAP_FPS] / 10, inf[I_CAP_FPS] % 10,
                     inf[I_ENC_FPS] / 10, inf[I_ENC_FPS] % 10, inf[I_DEC_FPS] / 10, inf[I_DEC_FPS] % 10))
        lines.append(u"lat %d ms  %d kbit/s" % (inf[I_LAT], inf[I_BPS] * 8 / 1000))
        cam = CAMS[0]
        if inf[I_CAM] == 1:
            cam = CAMS[1]
        lines.append(u"err %d drop %d  cam %s" % (inf[I_ERRORS], inf[I_DROPS], cam))
        sz = SIZES[self.size_i]
        lines.append(u"%dx%d %dfps %dk f%d%s" % (sz[0], sz[1], FPSES[self.fps_i], RATES[self.rate_i], self.flags,
                     self.paused and u" PAUSED" or u""))
        return lines

    def log_stats(self, inf):
        log("stats: cap=%d enc=%d dec=%d (fps x10) lat=%d ms %d B/s err=%d drops=%d cam=%d enc_ok=%d dec_ok=%d "
            "frames dec=%d prev=%d dec %dx%d pat=%d lay=%d rc=%d/%d state=%d" % (
            inf[I_CAP_FPS], inf[I_ENC_FPS], inf[I_DEC_FPS], inf[I_LAT], inf[I_BPS], inf[I_ERRORS], inf[I_DROPS],
            inf[I_CAM], inf[I_ENC_OK], inf[I_DEC_OK], inf[I_DEC_COUNT], inf[I_PREV_COUNT], inf[I_DEC_W],
            inf[I_DEC_H], inf[I_DEC_PATTERN], inf[I_DEC_LAYOUT], self.dec_rc, self.prev_rc, inf[I_STATE]))

    # ---------------------------------------------------------- drawing
    def redraw_if_needed(self):
        if self.dirty:
            self.draw()

    def redraw(self, rect=None):
        self.dirty = 1
        self.draw()

    def draw(self):
        self.dirty = 0
        if self.canvas is None or self.screen is None:
            return
        w, h = self.canvas.size
        scr = self.screen
        scr.clear(0x000000)
        if self.img_dec is not None and self.dec_size[0] > 0:
            dw, dh = self.dec_size
            tw = w
            th = w * dh / dw
            if th > h:
                th = h
                tw = h * dw / dh
            x1 = (w - tw) / 2
            y1 = (h - th) / 2
            scr.blit(self.img_dec, target=(x1, y1, x1 + tw, y1 + th), scale=1)
        if self.img_prev is not None and self.prev_size[0] > 0:
            pw = w / 3
            ph = pw * self.prev_size[1] / self.prev_size[0]
            scr.blit(self.img_prev, target=(w - pw - 2, h - ph - 2, w - 2, h - 2), scale=1)
            scr.rectangle((w - pw - 3, h - ph - 3, w - 1, h - 1), outline=0xffffff)
        y = 14
        if self.info is not None:
            for ln in self.stats_lines(self.info):
                scr.text((3, y), ln, fill=0xffff00)
                y = y + 14
        else:
            scr.text((3, y), u"waiting for helper...", fill=0xffff00)
        if self.msg:
            scr.text((3, h / 2), self.msg, fill=0xff4040)
        self.canvas.blit(scr)


def main():
    m = Mirror()
    m.start()
    m.lock.wait()      # keeps the script (and the app) alive until exit
    return m


try:
    _VM_NO_MAIN
except NameError:
    _APP = main()
