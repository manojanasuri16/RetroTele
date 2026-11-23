# CallVideo: SEND-ONLY video for a 2.7.7 call (the other person sees us; we keep
# hearing and sending audio as before). Python only drives the helpers, it never
# touches a video packet:
#   tgvideo.exe  camera -> H.264 baseline encoder (+ loopback decoder for the self-view);
#                commands on UDP 127.0.0.1:47012, status lines on 127.0.0.1:47011,
#                encoder units to tgcallaudio.exe on 127.0.0.1:47014 ("E 1")
#   tgcallaudio.exe  signalling (VideoFormats, RemoteMediaState, VideoParameters), RFC 6184
#                packets, RTCP, PLI handling; told "V1"/"V0" through CallAudio.set_video()
#   tgvdisp.pyd  draws the loopback-decoded picture into a graphics.Image (self-view)
# Voice-only calls never import this module's helpers; if anything here fails the call
# goes on (we just show a message). Python 2.2 compatible. e32socket rule: sockets are
# never close()d while the app runs, so ONE shared status socket is kept.

import sys
import types
import socket
import e32

HOST = "127.0.0.1"
PORT_CMD = 47012
PORT_STATUS = 47011

# Quality ladder (width, height, fps, kbit/s, encoder picture quality 0..100). The software encoder
# (uid 0x20001c13) only reaches 3-6 fps at 320x240 next to the call audio on the N79 (measured
# 0.14.2), but keeps up with the camera at QCIF. The 0.14.5 logs show it spends only ~50 kbit/s
# whatever the target is (bitrate 128 and 256 gave the same output in the bench), so the "picture
# quality" number is what can buy sharpness (UNTESTED guess: 80); steps down to cheaper settings
# when it drops frames, exceeds its budget or the peer reports loss, and up again after 30 clean
# seconds (never back to a level that already failed).
LEVELS = [(176, 144, 15, 128, 80), (176, 144, 15, 90, 65), (176, 144, 12, 56, 50)]
LEVEL_NAMES = [u"", u" (reduced quality)", u" (low rate)"]
VIDEO_W = LEVELS[0][0]
VIDEO_H = LEVELS[0][1]
VIDEO_FPS = LEVELS[0][2]
VIDEO_KBPS = LEVELS[0][3]
WARMUP_S = 8            # seconds after the pipeline runs before judging it
BAD_LIMIT = 6           # bad seconds in a row that trigger a step down
LOSS_BAD = 40           # RTCP loss fraction (of 256) counted as a bad second (about 16 percent)
SLOW_FPS10 = 85         # encoder output below 8.5 fps AND more than 2 fps behind the camera: bad second
UP_SECONDS = 30         # clean seconds before a step up
OVER_BUDGET = 130       # percent of the target bit rate that counts as a bad second
# Degrees clockwise baked into the pixels before encoding. The 2.7.7 protocol (V0) has no
# rotation extension, so a portrait picture would need rotating by us. Only 0 (landscape,
# the sensor's natural QCIF 176x144) is implemented in tgvideo.exe; others are logged there.
VIDEO_ROTATION_DEG = 0

CAM_REAR = 0
CAM_FRONT = 1
CAM_NAMES = [u"rear", u"front"]

TICK = 0.2

S_IDLE = 0
S_STARTING = 1      # exe launched, waiting until it reports "idle"
S_WAIT_RUN = 2      # S sent, waiting until the camera + encoder run
S_RUNNING = 3
S_FAILED = 4
S_RXSTART = 5       # helper launched only to show the peer's picture (no camera), waiting for hello
S_RXIDLE = 6        # helper up, camera off: the peer's picture is decoded and shown

# tgvdisp.info() word indexes (native/tgvideo/tgvshared.h)
I_STATE = 2
I_DEC_COUNT = 4
I_DEC_W = 5
I_DEC_H = 6
I_PREV_COUNT = 11
I_PREV_W = 12
I_PREV_H = 13
I_RX_STATE = 28     # 0 none, 1 decoder starting, 2 decoding, 3 setup failed, 4 no picture, 5 fatal
I_RX_ERR = 29
I_RX_W = 30
I_RX_H = 31
I_RX_PROFILE = 32
I_RX_LEVEL = 33
I_RX_AU = 34
I_RX_FED = 35
I_RX_DEC = 36
PROFILE_NAMES = {66: u"Baseline", 77: u"Main", 88: u"Extended", 100: u"High", 110: u"High 10",
                 122: u"High 4:2:2", 244: u"High 4:4:4"}


def _raw(sock):
    return getattr(sock, "_sock", sock)


def _is_err(res):
    return (type(res) is types.TupleType and len(res) == 2 and
            type(res[0]) in (types.ClassType, types.TypeType))


_SHARED = [None]        # the one status socket on 127.0.0.1:47011
_CURRENT = [None]       # the CallVideo receiving it
_PENDING = [0]


def _dispatch(res):
    _PENDING[0] = 0
    cv = _CURRENT[0]
    data = None
    if _is_err(res):
        pass
    elif type(res) is types.TupleType and len(res) == 2:
        data = res[0]
    elif type(res) is types.StringType:
        data = res
    if cv is not None and cv.helper_up():
        cv._arm()
        if data:
            cv.on_status(data)


def parse_stats(line):
    """'T st cam w h capfps10 encfps10 decfps10 lat bps err drops enc dec' -> (encfps10, bytes/s,
    drops, capfps10) or None."""
    if line[:2] != "T ":
        return None
    parts = line.split()
    if len(parts) < 13:
        return None
    try:
        return (int(parts[6]), int(parts[9]), int(parts[11]), int(parts[5]))
    except:
        return None


def parse_status(line):
    """'T hello' -> 2 (idle); 'T st cam w h ...' -> st (0 starting 1 running 2 idle 3 error
    4 quitting). None for anything else."""
    if line[:7] == "T hello":
        return 2
    if line[:2] != "T ":
        return None
    parts = line.split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except:
        return None


class CallVideo:
    def __init__(self, audio=None, on_change=None, log=None):
        self.audio = audio
        self.on_change = on_change
        self.logf = log
        self.state = S_IDLE
        self.cam = CAM_FRONT
        self.msg = u""
        self.hstate = -1
        self.ticks = 0
        self.t_s = 0
        self.t_run = 0
        self.resent_s = 0
        self.t_switch = 0
        self.timer = None
        self.sock = None
        self.tgvdisp = None
        self.attached = 0
        self.img = None
        self.img_size = (0, 0)
        self.last_dec = -1
        self.frame_new = 0
        self.errors = 0
        self.stopping = 0
        self.rx_lines = 0
        self.level = 0
        self.bad = 0
        self.good_s = 0
        self.t_level = 0
        self.last_drops = 0
        self.steps = 0
        self.ceiling = 0
        self.t_up = 0
        self.show_self = 0      # own picture hidden by default (smoother sending); key 7 shows it
        self.last_flags = -1
        self.rx_on = 0          # the helper also shows the peer's picture
        self.fwd_on = 0         # told the engine to forward the peer's access units
        self.want_send = 0
        self.err = u""
        self.inf = None
        self.pimg = None
        self.pimg_size = (0, 0)
        self.p_last = -1
        self.rx_at_s = 0

    # ------------------------------------------------------------ helpers
    def log(self, msg):
        f = self.logf
        if f is not None:
            try:
                f("video: " + msg)
            except:
                pass

    def active(self):
        """Our camera video is on or starting."""
        return (self.state == S_STARTING or self.state == S_WAIT_RUN or
                self.state == S_RUNNING)

    def helper_up(self):
        return self.state != S_IDLE and self.state != S_FAILED

    def changed(self):
        cb = self.on_change
        if cb is not None:
            try:
                cb()
            except:
                self.errors = self.errors + 1

    def status_text(self):
        """One line for the call screen."""
        if self.state == S_IDLE:
            return u""
        if self.state == S_FAILED:
            return self.msg
        if self.state == S_RXSTART or self.state == S_RXIDLE:
            return self.err
        cam = CAM_NAMES[self.cam]
        if self.state == S_RUNNING:
            if self.t_switch and self.ticks - self.t_switch < 12:
                return u"Video on - switching camera..."
            if self.t_level and self.ticks - self.t_level < 20:
                return u"Video on - adjusting quality..."
            return u"Video on - " + cam + u" camera" + LEVEL_NAMES[self.level]
        return u"Starting video (" + cam + u" camera)..."

    def _open(self):
        s = _SHARED[0]
        if s is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((HOST, PORT_STATUS))
            _SHARED[0] = s
        return s

    def _arm(self):
        _CURRENT[0] = self
        if self.sock is None or _PENDING[0]:
            return
        _PENDING[0] = 1
        try:
            _raw(self.sock).recvfrom(512, 0, _dispatch)
        except:
            _PENDING[0] = 0
            self.errors = self.errors + 1

    def send(self, data):
        if self.sock is None:
            return 0
        try:
            _raw(self.sock).sendto(data, 0, (HOST, PORT_CMD))
            return 1
        except:
            self.errors = self.errors + 1
            self.log("sendto failed: " + str(sys.exc_info()[1]))
            return 0

    def on_status(self, data):
        self.rx_lines = self.rx_lines + 1
        st = parse_status(data)
        if self.rx_lines <= 3 or (st is not None and st != self.hstate):
            self.log("helper status #%d: %s" % (self.rx_lines, data[:90]))
        if st is not None:
            self.hstate = st
            if st == 1 and self.state == S_RUNNING:
                sts = parse_stats(data)
                if sts is not None:
                    self.judge(sts)

    def peer_loss(self):
        """RTCP loss fraction (0..255) the peer last reported for our video."""
        a = self.audio
        try:
            return int(getattr(a, "loss", 0))
        except:
            return 0

    def judge(self, sts):
        """Once a second while running: step down when the encoder cannot keep up (drops, lagging
        behind the camera), spends more than its budget or the peer reports loss; step up after
        UP_SECONDS clean seconds, but never to a level that failed shortly after a step up."""
        if self.t_switch and self.ticks - self.t_switch < 60:
            return
        if self.t_level and self.ticks - self.t_level < WARMUP_S * 5:
            self.last_drops = sts[2]
            return
        if self.t_run and self.ticks - self.t_run < WARMUP_S * 5:
            self.last_drops = sts[2]
            return
        fps10, bps, drops, cap10 = sts
        newdrops = drops - self.last_drops
        self.last_drops = drops
        loss = self.peer_loss()
        bad = 0
        if fps10 < SLOW_FPS10 and cap10 - fps10 > 20:
            bad = 1
        if newdrops >= 3:
            bad = 1
        if loss >= LOSS_BAD:
            bad = 1
        if bps * 8 > LEVELS[self.level][3] * 10 * OVER_BUDGET:
            bad = 1
        last = len(LEVELS) - 1
        if bad:
            self.good_s = 0
            self.bad = self.bad + 1
            if self.bad >= BAD_LIMIT and self.level < last:
                self.move_level(1, fps10, newdrops)
        else:
            if self.bad > 0:
                self.bad = self.bad - 1
            if newdrops == 0 and loss < 10:
                self.good_s = self.good_s + 1
            else:
                self.good_s = 0
            if self.good_s >= UP_SECONDS and self.level > self.ceiling:
                self.move_level(-1, fps10, newdrops)

    def move_level(self, d, fps10, newdrops):
        if d > 0:
            if self.t_up and self.ticks - self.t_up < 60 * 5:
                self.ceiling = self.level + 1          # that level failed right after a step up
        else:
            self.t_up = self.ticks
        self.level = self.level + d
        self.steps = self.steps + 1
        self.bad = 0
        self.good_s = 0
        self.t_level = self.ticks
        self.log("quality %s -> level %d %s (fps10 %d, drops +%d, peer loss %d, ceiling %d)" % (
            d > 0 and "down" or "up", self.level, str(LEVELS[self.level]), fps10, newdrops,
            self.peer_loss(), self.ceiling))
        try:
            self.audio.loss = 0
        except:
            pass
        self.send(self.params())
        self.changed()

    def set_audio_video(self, flag):
        a = self.audio
        if a is not None:
            try:
                a.set_video(flag)
            except:
                self.errors = self.errors + 1

    # ------------------------------------------------------------ start / stop
    def reset_counters(self):
        self.msg = u""
        self.err = u""
        self.resent_s = 0
        self.t_switch = 0
        self.last_dec = -1
        self.stopping = 0
        self.rx_lines = 0
        self.level = 0
        self.bad = 0
        self.good_s = 0
        self.t_level = 0
        self.last_drops = 0
        self.steps = 0
        self.ceiling = 0
        self.t_up = 0

    def launch(self, newstate):
        """Start tgvideo.exe (it waits for commands; the camera is only used after "S"). A helper
        that is already running (heard earlier) is reused, never started twice."""
        alive = (self.hstate == 1 or self.hstate == 2)
        if not alive:
            self.hstate = -1
        self.ticks = 0
        self.reset_counters()
        self.fwd_on = 0
        try:
            import tgvdisp
            self.tgvdisp = tgvdisp
        except:
            self.tgvdisp = None
            self.log("tgvdisp missing: no self-view and no peer picture")
        try:
            self.sock = self._open()
        except:
            return self.fail(u"Video: cannot open UDP port 47011")
        self._arm()
        if alive:
            self.log("helper already running, reusing it")
            self.send("P")                       # it answers with its status line
        else:
            try:
                e32.start_exe(u"tgvideo.exe", u"")
            except:
                return self.fail(u"Video helper tgvideo.exe is missing")
        self.state = newstate
        self.timer = e32.Ao_timer()
        self.timer.after(TICK, self.tick)
        self.changed()
        return 1

    def start_rx(self):
        """Peer video only: launch the helper without the camera so the peer's picture can be
        decoded and drawn. Returns 1 if the helper could be started."""
        if self.helper_up():
            self.rx_on = 1
            return 1
        self.rx_on = 1
        self.want_send = 0
        self.log("helper started for the peer's picture")
        return self.launch(S_RXSTART)

    def start(self, cam=CAM_FRONT):
        """Start our camera video; the helper is launched first if it is not running. The
        pipeline starts when it is ready. Returns 1 if the helper could be started (progress
        via on_change / status_text)."""
        if self.active():
            return 1
        self.cam = cam
        self.want_send = 1
        if self.state == S_RXIDLE or self.state == S_RXSTART:
            self.reset_counters()
            self.log("camera video on (helper already running), camera %d" % self.cam)
            if self.state == S_RXIDLE:
                self.state = S_STARTING
                self.ticks = 0
            self.changed()
            return 1
        r = self.launch(S_STARTING)
        if r:
            self.log("helper started, camera %d" % self.cam)
        return r

    def fail(self, text):
        """Camera/helper trouble: tell the engine to stop sending, release the camera,
        keep the call alive. When the helper also shows the peer's picture it keeps running."""
        self.log("FAILED: %s (helper state %s, %d status lines heard, tick %d, errors %d)" % (
            str(text), str(self.hstate), self.rx_lines, self.ticks, self.errors))
        self.set_audio_video(0)
        if self.rx_on and self.fwd_on and self.hstate != 4 and self.state != S_STARTING:
            self.send("E 0")
            self.send("T")
            self.img = None
            self.err = text
            self.state = S_RXIDLE
            self.changed()
            return 0
        self.release_helper()
        self.msg = text
        self.state = S_FAILED
        self.changed()
        return 0

    def release_helper(self):
        self.send("E 0")
        self.send("Q")
        if self.attached and self.tgvdisp is not None:
            try:
                self.tgvdisp.detach()
            except:
                pass
        self.attached = 0
        self.img = None
        self.img_size = (0, 0)

    def stop(self):
        """Video off / call over: stop sending and release the camera (waits briefly for
        the helper to confirm). Safe to call at any time and more than once."""
        if self.state == S_IDLE:
            return
        self.stopping = 1
        self.log("stop")
        self.set_audio_video(0)
        self.set_fwd(0)
        self.rx_on = 0
        self.send("E 0")
        n = 0
        while n < 15:
            self.send("Q")             # resent: a helper that is still starting misses the first
            try:
                e32.ao_sleep(0.1)
            except:
                pass
            n = n + 1
            if self.hstate == 4:
                break
        if self.attached and self.tgvdisp is not None:
            try:
                self.tgvdisp.detach()
            except:
                pass
        self.attached = 0
        self.img = None
        self.img_size = (0, 0)
        self.pimg = None
        self.pimg_size = (0, 0)
        self.p_last = -1
        self.inf = None
        self.state = S_IDLE
        self.msg = u""
        self.err = u""
        self.timer = None
        self.changed()

    def stop_send(self):
        """Our camera video off. If the helper is also showing the peer's picture it keeps
        running (camera and encoder released); otherwise it is stopped completely."""
        if not self.active():
            return
        if not (self.rx_on and self.fwd_on):
            self.stop()
            return
        self.log("camera video off, helper stays for the peer's picture")
        self.set_audio_video(0)
        self.send("E 0")
        self.send("T")
        self.img = None
        self.img_size = (0, 0)
        self.err = u""
        self.t_switch = 0
        self.state = S_RXIDLE
        self.changed()

    def set_fwd(self, flag):
        """Tell the call engine whether tgvideo.exe takes the peer's access units."""
        if (flag and 1 or 0) == self.fwd_on:
            return
        self.fwd_on = flag and 1 or 0
        a = self.audio
        if a is not None:
            try:
                a.set_rxfwd(self.fwd_on)
            except:
                self.errors = self.errors + 1

    def toggle_self(self):
        """Show / hide our own picture (hiding saves the repaints)."""
        if self.show_self:
            self.show_self = 0
        else:
            self.show_self = 1
        self.last_dec = -1
        self.changed()
        return self.show_self

    def switch_camera(self):
        """Front <-> rear. The helper restarts the encoder: new SPS/PPS + IDR; RTP seq, SSRC
        and timestamps continue (they live in tgcallaudio.exe)."""
        if self.state != S_RUNNING:
            return 0
        self.cam = 1 - self.cam
        self.t_switch = self.ticks
        self.log("switch camera -> %d" % self.cam)
        self.send("C %d" % self.cam)
        self.changed()
        return 1

    # ------------------------------------------------------------ progress
    def params(self):
        w, h, fps, kbps, q = LEVELS[self.level]
        return "S %d %d %d %d %d %d %d" % (w, h, fps, kbps, self.cam, VIDEO_ROTATION_DEG, q)

    def tick(self):
        if self.state == S_IDLE or self.state == S_FAILED or self.stopping:
            return
        self.ticks = self.ticks + 1
        self.timer.after(TICK, self.tick)
        try:
            self.step()
        except:
            self.errors = self.errors + 1
            self.log("tick error: " + str(sys.exc_info()[1]))

    def step(self):
        hs = self.hstate
        if hs == -1 and self.ticks > 0 and self.ticks % 10 == 0 and (
                self.state == S_RXSTART or self.state == S_STARTING):
            self.send("P")                       # the hello may have been missed: ask again
        if self.state == S_RXSTART:
            if hs == 2:
                self.send("L 0")
                self.set_fwd(1)
                self.state = S_RXIDLE
                self.log("helper ready for the peer's picture")
                self.changed()
            elif self.ticks > 60:
                self.rx_on = 0
                self.fail(u"Peer video helper did not start")
        elif self.state == S_RXIDLE:
            self.update_frames()
        elif self.state == S_STARTING:
            if hs == 2:
                self.send("L 0")             # no loopback decoder: the self-view uses the camera frames
                self.set_fwd(self.rx_on)
                self.send(self.params())
                self.t_s = self.ticks
                self.rx_at_s = self.rx_lines
                self.state = S_WAIT_RUN
                self.log("sent " + self.params())
            elif self.ticks > 60:
                self.fail(u"Video helper did not start")
        elif self.state == S_WAIT_RUN:
            if hs == 1:
                self.state = S_RUNNING
                self.t_run = self.ticks
                self.send("E 1")
                self.set_audio_video(1)
                self.log("camera + encoder running; sending enabled")
                self.changed()
            elif hs == 3:
                self.fail(u"Camera is in use or unavailable")
            elif hs == 2 and self.ticks - self.t_s > 32 and not self.resent_s:
                self.resent_s = 1                    # the helper still idles: S was lost
                self.send(self.params())
            elif self.ticks - self.t_s > 100:
                if self.rx_lines == self.rx_at_s:
                    self.fail(u"Video helper is not responding")
                else:
                    self.fail(u"Camera did not start")
        elif self.state == S_RUNNING:
            if hs == 3:
                self.fail(u"Camera error, video stopped")
                return
            if self.t_switch and self.ticks - self.t_switch == 12:
                self.send("K")                       # belt and braces after a camera switch
                self.changed()
            self.update_frames()

    # ------------------------------------------------------------ self-view
    def attach(self):
        td = self.tgvdisp
        if td is None:
            return None
        if not self.attached:
            try:
                if td.attach() == 0:
                    self.attached = 1
            except:
                return None
            if not self.attached:
                return None
        try:
            return td.info()
        except:
            return None

    def update_frames(self):
        """Read the shared chunk: the peer's decoded picture (decoder output) and, while our
        camera is on, the camera preview (decimated by 2 for big frames, mirrored for the front
        camera; the QCIF-only loopback decoder is not used)."""
        inf = self.attach()
        self.inf = inf
        if inf is None:
            return
        if self.state == S_RUNNING and self.show_self and self.ticks % 2 == 0:
            self.update_self(inf)       # about 2.5 pictures per second: each one repaints the screen
        if self.rx_on and inf[I_RX_STATE] == 2:
            self.update_peer(inf)
        if self.rx_on and inf[I_RX_STATE] >= 3 and self.fwd_on:
            # no decoder can show this stream: stop receiving it (no CPU, no PLI/REMB traffic)
            self.log("peer video cannot be decoded (state %d, error %d): receiving stopped" % (
                inf[I_RX_STATE], inf[I_RX_ERR]))
            self.set_fwd(0)
            au = self.audio
            if au is not None:
                try:
                    au.set_rx(0)
                except:
                    self.errors = self.errors + 1

    def update_self(self, inf):
        td = self.tgvdisp
        if inf[I_PREV_COUNT] <= 0:
            return
        w = inf[I_PREV_W]
        h = inf[I_PREV_H]
        if w <= 0 or h <= 0:
            return
        if w >= 300:
            w = w / 2
            h = h / 2
        if self.img is None or self.img_size != (w, h):
            try:
                import graphics
                self.img = graphics.Image.new((w, h), 'RGB16')
                self.img_size = (w, h)
                self.last_dec = -1
            except:
                self.img = None
                return
        flags = 0
        if self.cam == CAM_FRONT:
            flags = 4
        if flags != self.last_flags:
            self.last_flags = flags
            self.last_dec = -1
        try:
            rc = td.render(self.img, 1, flags, self.last_dec)
        except:
            return
        if rc >= 0 and rc != self.last_dec:
            self.last_dec = rc
            self.frame_new = 1
            self.changed()

    def update_peer(self, inf):
        td = self.tgvdisp
        if inf[I_DEC_COUNT] <= 0:
            return
        w = inf[I_DEC_W]
        h = inf[I_DEC_H]
        if w <= 0 or h <= 0:
            return
        if w >= 320 or h >= 400:
            w = w / 2
            h = h / 2
        if self.pimg is None or self.pimg_size != (w, h):
            try:
                import graphics
                self.pimg = graphics.Image.new((w, h), 'RGB16')
                self.pimg_size = (w, h)
                self.p_last = -1
            except:
                self.pimg = None
                return
        try:
            rc = td.render(self.pimg, 0, 0, self.p_last)
        except:
            return
        if rc >= 0 and rc != self.p_last:
            self.p_last = rc
            self.frame_new = 1
            self.changed()

    def peer_frame(self):
        """(image, w, h) of the peer's newest decoded picture, or None."""
        inf = self.inf
        if (not self.rx_on or inf is None or inf[I_RX_STATE] != 2 or self.pimg is None or
                self.p_last < 0):
            return None
        return (self.pimg, self.pimg_size[0], self.pimg_size[1])

    def peer_status(self):
        """One line about the peer's video decoding, or u"" when nothing is known yet."""
        inf = self.inf
        if not self.rx_on or inf is None or not self.helper_up():
            return u""
        st = inf[I_RX_STATE]
        w = inf[I_RX_W]
        h = inf[I_RX_H]
        prof = PROFILE_NAMES.get(inf[I_RX_PROFILE], u"profile %d" % inf[I_RX_PROFILE])
        if st == 2:
            if inf[I_DEC_COUNT] > 0 and self.p_last >= 0:
                return u"Peer video: receiving %dx%d" % (w, h)
            return u"Peer video: waiting for the first picture"
        if st == 1:
            return u"Peer video: starting decoder (%dx%d, %s)" % (w, h, prof)
        if st == 3:
            return u"Peer video: decoder setup failed (error %d, %s profile)" % (inf[I_RX_ERR], prof)
        if st == 4:
            return u"Peer video: decoder cannot decode this stream (%s profile)" % prof
        if st == 5:
            return u"Peer video: decoder error %d" % inf[I_RX_ERR]
        if inf[I_RX_AU] > 0:
            return u"Peer video: starting..."
        return u""

    def peer_failed(self):
        inf = self.inf
        return inf is not None and self.rx_on and inf[I_RX_STATE] >= 3

    def frame(self):
        """(image, w, h) of the self-view or None."""
        if self.state != S_RUNNING or not self.show_self or self.img is None or self.last_dec < 0:
            return None
        return (self.img, self.img_size[0], self.img_size[1])
