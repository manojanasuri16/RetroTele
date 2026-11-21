# Live check against Telegram (PC, Python 2.7): key exchange + one encrypted call.
import sys, os, time, threading
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import pcnet, tl, mtproto

schema = tl.Schema(os.path.join(HERE, "..", "schema.txt"))
net = pcnet.SelectNet()
result = {}

class Ev:
    def log(self, m): print "LOG", m
    def status(self, m): print "STATUS", m
    def saved(self, s): pass
    def update(self, o): print "UPDATE", o.get("_")
    def connected(self, s): print "CONNECTED"
    def disconnected(self, s, why): print "DISCONNECTED", why

w = tl.Writer(schema)
def init_query(inner):
    return w.obj({"_": "invokeWithLayer", "layer": schema.layer, "query": tl.Raw(w.obj({
        "_": "initConnection", "api_id": int(os.environ.get("API_ID", "1")),
        "device_model": "PC test", "system_version": "Linux", "app_version": "0.1",
        "system_lang_code": "en", "lang_pack": "", "lang_code": "en",
        "query": tl.Raw(inner)}))})

s = mtproto.Session(net, schema, Ev(), 2, init_query=init_query)
t0 = time.time()
def ok(res):
    result["ok"] = res; net.stop()
def err(e):
    result["err"] = e; net.stop()
s.invoke({"_": os.environ.get("FUNC", "help.getNearestDc")}, ok, err)
net.later(60, net.stop)
net.run()
print "time %.1fs" % (time.time() - t0)
print result
