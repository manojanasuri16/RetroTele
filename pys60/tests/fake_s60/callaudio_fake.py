"""Test double for callaudio.CallAudio (no sockets, no helper)."""


class CallAudio:
    instances = []

    def __init__(self):
        self.on_packet = None
        self.sent = []
        self.running = 0
        self.rx = 0
        self.tx = 0
        self.errors = 0
        self.last_error = u""
        self.relay = None
        self.on_state = None
        self.on_info = None
        self.muted = 0
        self.route = 1
        self.want_mute = 0
        self.want_route = 1
        CallAudio.instances.append(self)

    def start_relay(self, key, is_outgoing, connections, on_state, iap=0):
        self.relay = (key, is_outgoing, connections)
        self.on_state = on_state
        self.running = 1
        return 1

    def start_relay277(self, key, is_outgoing, connections, on_state, iap=0, on_signal=None):
        self.relay = (key, is_outgoing, connections)
        self.v277 = 1
        self.on_state = on_state
        self.on_signal = on_signal
        self.signals = []
        self.running = 1
        return 1

    def send_signaling(self, data):
        self.signals.append(data)

    def helper_state(self, name):
        self.on_state(name)

    def set_mute(self, flag):
        self.want_mute = not not flag
        self.sent.append("M%d" % self.want_mute)

    def set_route(self, n):
        self.want_route = n
        self.sent.append("R%d" % n)

    def helper_info(self, muted, route):
        self.muted = muted
        self.route = route
        if self.on_info is not None:
            self.on_info()

    def start(self, on_packet, seconds=60):
        self.on_packet = on_packet
        self.running = 1

    def deliver(self, data):
        # the "helper" sends a packet to the app
        self.rx = self.rx + 1
        self.on_packet(data)

    def send(self, data):
        self.tx = self.tx + 1
        self.sent.append(data)

    def stop(self):
        self.running = 0
        self.on_state = None
        self.sent.append("Q")
