#!/usr/bin/env python3
"""Builds pys60/schema.txt (the compact TL schema the phone loads) from
api.tl + mtproto.tl (copies of Telegram Desktop's scheme files).

Every constructor is kept (any of them can arrive in an update); only the
functions RetroGram calls are kept, to save memory on the phone.

Line format:  C|F <hex id> <name> [param:type ...] =<Result type>
Run it again after updating the .tl files; LAYER is written to schema.txt.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "pys60", "schema.txt")

FUNCTIONS = """
req_pq_multi req_DH_params set_client_DH_params ping ping_delay_disconnect
get_future_salts destroy_session
invokeWithLayer initConnection invokeWithoutUpdates
help.getConfig help.getNearestDc
auth.sendCode auth.resendCode auth.signIn auth.signUp auth.checkPassword auth.logOut
auth.exportAuthorization auth.importAuthorization auth.cancelCode
account.getPassword account.updateStatus
users.getUsers users.getFullUser
contacts.getContacts contacts.resolveUsername contacts.search
messages.getDialogs messages.getHistory messages.sendMessage messages.readHistory
messages.getPeerDialogs messages.getMessages messages.setTyping messages.getDialogFilters
messages.editMessage messages.deleteMessages channels.deleteMessages messages.forwardMessages
phone.discardCall phone.receivedCall messages.getDhConfig phone.requestCall
phone.acceptCall phone.confirmCall
messages.getFullChat channels.getFullChannel account.updateNotifySettings
channels.readHistory channels.getMessages
updates.getState updates.getDifference updates.getChannelDifference
upload.getFile
""".split()

LINE = re.compile(r"^([a-zA-Z0-9_.]+)#([0-9a-f]+)\s*(.*?)\s*=\s*([^;]+);")


def parse(path):
    section = "types"
    out = []
    for raw in open(path, encoding="utf-8"):
        line = raw.split("//")[0].strip()
        if not line:
            continue
        if line == "---functions---":
            section = "functions"
            continue
        if line == "---types---":
            section = "types"
            continue
        m = LINE.match(line)
        if not m:
            continue
        name, cid, params, result = m.groups()
        ps = []
        for p in params.split():
            if p.startswith("{"):
                continue           # {X:Type} generic declaration
            ps.append(p)
        out.append((section, name, int(cid, 16), ps, result.strip()))
    return out


def main():
    layer = None
    for raw in open(os.path.join(HERE, "api.tl"), encoding="utf-8"):
        m = re.match(r"//\s*LAYER\s+(\d+)", raw.strip())
        if m:
            layer = int(m.group(1))
    if layer is None:
        sys.exit("LAYER not found in api.tl")
    seen = {}
    lines = []
    funcs = {}
    for path in ("mtproto.tl", "api.tl"):
        for section, name, cid, ps, result in parse(os.path.join(HERE, path)):
            if section == "functions":
                if name in FUNCTIONS:
                    funcs[name] = 1
                    lines.append("F %08x %s %s =%s" % (cid, name, " ".join(ps), result))
                continue
            if cid in seen:
                continue
            seen[cid] = 1
            lines.append("C %08x %s %s =%s" % (cid, name, " ".join(ps), result))
    missing = [f for f in FUNCTIONS if f not in funcs]
    if missing:
        sys.exit("functions not found: %s" % missing)
    lines = [re.sub(r"  +", " ", l) for l in lines]
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("LAYER %d\n" % layer)
        f.write("\n".join(lines) + "\n")
    print("wrote %s: layer %d, %d lines, %d bytes" % (OUT, layer, len(lines) + 1,
                                                      os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
