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

VIDEO_W = 176
VIDEO_H = 144
VIDEO_FPS = 15
VIDEO_KBPS = 60
# Degrees clockwise baked into the pixels before encoding. The 2.7.7 protocol (V0) has no
# rotation extension, so a portrait picture would need rotating by us. Only 0 (landscape,
# the sensor's natural QCIF 176x144) is implemented in tgvideo.exe; others are logged there.
VIDEO_ROTATION_DEG = 0

CAM_REAR = 0
CAM_FRONT = 1
CAM_NAMES = [u"rear", u"front"]

TICK = 0.25

S_IDLE = 0
S_STARTING = 1      # exe launched, waiting until it reports "idle"
S_WAIT_RUN = 2      # S sent, waiting until the camera + encoder run
S_RUNNING = 3
S_FAILED = 4

# tgvdisp.info() word indexes (native/tgvideo/tgvshared.h)
I_STATE = 2
I_DEC_COUNT = 4
I_DEC_W = 5
I_DEC_H = 6


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
    if cv is not None and cv.active():
        cv._arm()
        if data:
            cv.on_status(data)


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

    # ------------------------------------------------------------ helpers
    def log(self, msg):
        f = self.logf
        if f is not None:
            try:
                f("video: " + msg)
            except:
                pass

    def active(self):
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
        cam = CAM_NAMES[self.cam]
        if self.state == S_RUNNING:
            if self.t_switch and self.ticks - self.t_switch < 12:
                return u"video on, switching camera..."
            return u"video on, camera: " + cam
        return u"video starting (camera: " + cam + u")..."

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

    def set_audio_video(self, flag):
        a = self.audio
        if a is not None:
            try:
                a.set_video(flag)
            except:
                self.errors = self.errors + 1

    # ------------------------------------------------------------ start / stop
    def start(self, cam=CAM_FRONT):
        """Launch the camera helper; the pipeline starts when it is ready. Returns 1 if
        the helper could be started (progress via on_change / status_text)."""
        if self.active():
            return 1
        self.cam = cam
        self.msg = u""
        self.hstate = -1
        self.ticks = 0
        self.resent_s = 0
        self.t_switch = 0
        self.last_dec = -1
        self.stopping = 0
        self.rx_lines = 0
        try:
            import tgvdisp
            self.tgvdisp = tgvdisp
        except:
            self.tgvdisp = None
            self.log("tgvdisp missing: no self-view")
        try:
            self.sock = self._open()
        except:
            return self.fail(u"Video: cannot open UDP port 47011")
        self._arm()
        try:
            e32.start_exe(u"tgvideo.exe", u"")
        except:
            return self.fail(u"Video helper tgvideo.exe is missing")
        self.state = S_STARTING
        self.log("helper started, camera %d" % self.cam)
        self.timer = e32.Ao_timer()
        self.timer.after(TICK, self.tick)
        self.changed()
        return 1

    def fail(self, text):
        """Camera/helper trouble: tell the engine to stop sending, release the camera,
        keep the call alive."""
        self.log("FAILED: %s (helper state %s, %d status lines heard, tick %d, errors %d)" % (
            str(text), str(self.hstate), self.rx_lines, self.ticks, self.errors))
        self.set_audio_video(0)
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
        self.state = S_IDLE
        self.msg = u""
        self.timer = None
        self.changed()

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
        return "S %d %d %d %d %d %d" % (VIDEO_W, VIDEO_H, VIDEO_FPS, VIDEO_KBPS, self.cam,
                                        VIDEO_ROTATION_DEG)

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
        if self.state == S_STARTING:
            if hs == 2:
                self.send(self.params())
                self.t_s = self.ticks
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
                self.fail(u"Camera did not start")
        elif self.state == S_RUNNING:
            if hs == 3:
                self.fail(u"Camera error, video stopped")
                return
            if self.t_switch and self.ticks - self.t_switch == 12:
                self.send("K")                       # belt and braces after a camera switch
                self.changed()
            self.update_frame()

    # ------------------------------------------------------------ self-view
    def update_frame(self):
        """Pull the newest loopback-decoded picture (about 4 per second is plenty)."""
        td = self.tgvdisp
        if td is None:
            return
        if not self.attached:
            try:
                if td.attach() == 0:
                    self.attached = 1
            except:
                return
            if not self.attached:
                return
        try:
            inf = td.info()
        except:
            return
        if inf is None or inf[I_DEC_COUNT] <= 0:
            return
        w = inf[I_DEC_W]
        h = inf[I_DEC_H]
        if w <= 0 or h <= 0:
            return
        if self.img is None or self.img_size != (w, h):
            try:
                import graphics
                self.img = graphics.Image.new((w, h), 'RGB16')
                self.img_size = (w, h)
                self.last_dec = -1
            except:
                self.img = None
                return
        try:
            rc = td.render(self.img, 0, 0, self.last_dec)
        except:
            return
        if rc >= 0 and rc != self.last_dec:
            self.last_dec = rc
            self.frame_new = 1
            self.changed()

    def frame(self):
        """(image, w, h) of the self-view or None."""
        if self.state != S_RUNNING or self.img is None or self.last_dec < 0:
            return None
        return (self.img, self.img_size[0], self.img_size[1])
