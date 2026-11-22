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
        CallAudio.instances.append(self)

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
        self.sent.append("Q")
