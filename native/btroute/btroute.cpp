// tgbtroute.exe: call audio routing to a Bluetooth headset (or explicitly to the phone's earpiece
// while a headset is connected) for RetroTele calls, through S60's Telephony Audio Routing API.
//
// Why a separate process: the S60 3.2 SDK ships this API only for the emulator (no ARM header,
// no import library), and the VoIP Audio Services stream can only choose "handset" (private)
// or "loudspeaker". With a Bluetooth headset connected, private audio is meant for the headset
// but nothing opened its audio link (0.15.1: no sound, no mic). So this helper loads
// TelephonyAudioRouting.dll at run time, finds CTelephonyAudioRouting::NewL among the first
// exports (on the emulator ordinal 1 is the constructor, 2 NewL; the ARM ordinals are not
// documented) and calls the class through its virtual functions. A wrong guess can crash only
// this process: every attempt is written to C:\Data\retrotele_btroute.cfg first, so the next
// start skips an ordinal that crashed. tgcallaudio.exe starts it when needed and restarts it a
// few times; the call never depends on it.
//
// Commands on UDP 127.0.0.1:47016: "R b" Bluetooth, "R h" handset, "R l" loudspeaker, "Q" quit.
// Answers to 127.0.0.1:47002 (tgcallaudio's control port): "b <state> <output> <outputs...>".
// Log: E:\retrotele_btroute.txt (C:\Data\ without a card).
#include <e32base.h>
#include <e32std.h>
#include <f32file.h>
#include <es_sock.h>
#include <in_sock.h>

// ---- Telephony Audio Routing API (declared here: the SDK has no ARM header) ----
class CTelephonyAudioRouting;
class MTelephonyAudioRoutingObserver
{
public:
    virtual void AvailableOutputsChanged(CTelephonyAudioRouting& aRouting) = 0;
    virtual void OutputChanged(CTelephonyAudioRouting& aRouting) = 0;
    virtual void SetOutputComplete(CTelephonyAudioRouting& aRouting, TInt aError) = 0;
    // spare slots: harmless if the real interface has more entries (they only log)
    virtual void Spare1(CTelephonyAudioRouting& aRouting) = 0;
    virtual void Spare2(CTelephonyAudioRouting& aRouting) = 0;
};
class CTelephonyAudioRouting : public CBase
{
public:
    enum TAudioOutput { ENotActive, ENone, EHandset, ELoudspeaker, EWiredAudioAccessory, EBTAudioAccessory, ETTY };
    virtual const TArray<TAudioOutput>& AvailableOutputs() = 0;
    virtual TAudioOutput Output() = 0;
    virtual void SetOutputL(TAudioOutput aOutput) = 0;
    virtual TAudioOutput PreviousOutput() = 0;
    virtual TInt SetShowNote(TBool aMode) = 0;
    virtual TInt GetShowNote(TBool& aMode) = 0;
};
typedef CTelephonyAudioRouting* (*TNewL)(MTelephonyAudioRoutingObserver&);

_LIT(KCfg, "C:\\Data\\retrotele_btroute.cfg");
static RFs gFs;
static RFile gLog;
static TBool gLogOk = EFalse;

static void Log(TRefByValue<const TDesC8> aFmt, ...)
{
    if (!gLogOk) return;
    VA_LIST l;
    VA_START(l, aFmt);
    TBuf8<200> b;
    b.FormatList(aFmt, l);
    VA_END(l);
    b.Append('\n');
    gLog.Write(b);
    gLog.Flush();
}

// ---- ordinal memory: "<ordinal> <result>" lines; result: bad (crashed/garbage), ctor, ok ----
static TInt gStatus[8];             // 0 unknown, 1 bad, 2 ctor, 3 ok
static void LoadCfg()
{
    Mem::FillZ(gStatus, sizeof(gStatus));
    RFile f;
    if (f.Open(gFs, KCfg, EFileRead) != KErrNone) return;
    TBuf8<256> b;
    f.Read(b);
    f.Close();
    TLex8 lx(b);
    while (!lx.Eos()) {
        TInt ord = 0;
        if (lx.Val(ord) != KErrNone) break;
        lx.SkipSpace();
        TPtrC8 w = lx.NextToken();
        lx.SkipSpace();
        if (ord < 1 || ord > 7) continue;
        if (w == _L8("bad") || w == _L8("trying")) gStatus[ord] = 1;   // "trying" left over = it crashed
        else if (w == _L8("ctor")) gStatus[ord] = 2;
        else if (w == _L8("ok")) gStatus[ord] = 3;
    }
}
static void SaveCfg(TInt aTrying)
{
    RFile f;
    gFs.MkDirAll(KCfg);
    if (f.Replace(gFs, KCfg, EFileWrite) != KErrNone) return;
    TBuf8<256> b;
    for (TInt i = 1; i < 8; i++) {
        if (i == aTrying) { b.AppendFormat(_L8("%d trying\n"), i); continue; }
        if (gStatus[i] == 1) b.AppendFormat(_L8("%d bad\n"), i);
        else if (gStatus[i] == 2) b.AppendFormat(_L8("%d ctor\n"), i);
        else if (gStatus[i] == 3) b.AppendFormat(_L8("%d ok\n"), i);
    }
    f.Write(b);
    f.Flush();
    f.Close();
}

// ---- the helper ----
static const TInt KMaxPkt = 64;
class CRouter;
static CRouter* gRouter = NULL;

class CRouter : public CActive, public MTelephonyAudioRoutingObserver
{
public:
    CRouter() : CActive(EPriorityStandard), iPtr(iBuf, 0, KMaxPkt) { CActiveScheduler::Add(this); }
    ~CRouter() { Cancel(); delete iRouting; iSock.Close(); iSs.Close(); iLib.Close(); }

    TBool CreateRouting()
    {
        TInt e = iLib.Load(_L("TelephonyAudioRouting.dll"));
        Log(_L8("load TelephonyAudioRouting.dll err %d"), e);
        if (e != KErrNone) return EFalse;
        LoadCfg();
        // a known good ordinal first, then 2 (NewL on the emulator), 1, 3, 4, 5
        const TInt order[6] = { 0, 2, 1, 3, 4, 5 };
        TInt good = 0;
        for (TInt i = 1; i < 8; i++) if (gStatus[i] == 3) good = i;
        for (TInt k = 0; k < 6; k++) {
            TInt ord = k == 0 ? good : order[k];
            if (ord <= 0 || (k > 0 && ord == good)) continue;
            if (gStatus[ord] == 1 || gStatus[ord] == 2) continue;
            TLibraryFunction fn = iLib.Lookup(ord);
            if (!fn) { Log(_L8("ordinal %d: none"), ord); continue; }
            SaveCfg(ord);                                  // if we crash now, the next start skips it
            Log(_L8("ordinal %d: calling as NewL"), ord);
            CTelephonyAudioRouting* r = NULL;
            TRAPD(err, r = ((TNewL)fn)(*this));
            Log(_L8("ordinal %d: returned %d (leave %d)"), ord, (TInt)r, err);
            if (err != KErrNone || r == NULL) { gStatus[ord] = 1; SaveCfg(0); continue; }
            if ((TAny*)r == (TAny*)this || (TAny*)r == (TAny*)(MTelephonyAudioRoutingObserver*)this) {
                // a constructor run on our object: it is not NewL (our object is fine to use? no:
                // its vtable may be overwritten - give up this run, the next start uses another)
                gStatus[ord] = 2; SaveCfg(0);
                Log(_L8("ordinal %d is a constructor, not NewL: restart needed"), ord);
                return EFalse;
            }
            iRouting = r;
            TInt out = r->Output();
            const TArray<CTelephonyAudioRouting::TAudioOutput>& av = r->AvailableOutputs();
            TInt n = av.Count();
            Log(_L8("ordinal %d: Output()=%d, %d available outputs"), ord, out, n);
            if (out < 0 || out > 6 || n < 0 || n > 7) { gStatus[ord] = 1; SaveCfg(0); iRouting = NULL; return EFalse; }
            gStatus[ord] = 3;
            SaveCfg(0);
            return ETrue;
        }
        Log(_L8("no usable NewL ordinal"));
        return EFalse;
    }

    void ReportL(const TDesC8& aWhat)
    {
        TBuf8<KMaxPkt> b;
        b.Format(_L8("b %S %d"), &aWhat, iRouting ? (TInt)iRouting->Output() : -1);
        if (iRouting) {
            const TArray<CTelephonyAudioRouting::TAudioOutput>& av = iRouting->AvailableOutputs();
            for (TInt i = 0; i < av.Count() && b.Length() < KMaxPkt - 4; i++) b.AppendFormat(_L8(" %d"), (TInt)av[i]);
        }
        Log(_L8("report: %S"), &b);
        TInetAddr to(INET_ADDR(127, 0, 0, 1), 47002);
        TRequestStatus st;
        iSock.SendTo(b, to, 0, st);
        User::WaitForRequest(st);
    }

    void StartL()
    {
        User::LeaveIfError(iSs.Connect());
        User::LeaveIfError(iSock.Open(iSs, KAfInet, KSockDatagram, KProtocolInetUdp));
        TInetAddr me(INET_ADDR(127, 0, 0, 1), 47016);
        User::LeaveIfError(iSock.Bind(me));
        Recv();
    }
    void Recv() { iPtr.Zero(); iSock.RecvFrom(iPtr, iFrom, 0, iStatus); SetActive(); }
    void RunL()
    {
        if (iStatus.Int() != KErrNone) { Log(_L8("recv err %d"), iStatus.Int()); CActiveScheduler::Stop(); return; }
        TBuf8<KMaxPkt> c(iPtr);
        Log(_L8("cmd %S"), &c);
        if (c.Length() >= 1 && c[0] == 'Q') { CActiveScheduler::Stop(); return; }
        if (c.Length() >= 3 && c[0] == 'R' && iRouting) {
            CTelephonyAudioRouting::TAudioOutput o = CTelephonyAudioRouting::EHandset;
            if (c[2] == 'b') o = CTelephonyAudioRouting::EBTAudioAccessory;
            else if (c[2] == 'l') o = CTelephonyAudioRouting::ELoudspeaker;
            TRAPD(e, iRouting->SetOutputL(o));
            Log(_L8("SetOutputL(%d) leave %d"), (TInt)o, e);
            TBuf8<16> w;
            w.Format(_L8("set%d_%d"), (TInt)o, e);
            ReportL(w);
        } else if (c.Length() >= 1 && c[0] == 'S') {
            ReportL(_L8("state"));
        }
        Recv();
    }
    void DoCancel() { iSock.CancelRecv(); }

    // observer: whatever slot the DLL calls, report the new state
    void Event(const TDesC8& aWhat)
    {
        Log(_L8("event %S"), &aWhat);
        TRAP_IGNORE(ReportL(aWhat));
    }
    void AvailableOutputsChanged(CTelephonyAudioRouting&) { Event(_L8("available")); }
    void OutputChanged(CTelephonyAudioRouting&) { Event(_L8("changed")); }
    void SetOutputComplete(CTelephonyAudioRouting&, TInt aError)
    {
        TBuf8<24> w;
        w.Format(_L8("complete_%d"), aError);
        Event(w);
    }
    void Spare1(CTelephonyAudioRouting&) { Event(_L8("spare1")); }
    void Spare2(CTelephonyAudioRouting&) { Event(_L8("spare2")); }

    CTelephonyAudioRouting* iRouting;
    RLibrary iLib;
    RSocketServ iSs;
    RSocket iSock;
    TUint8 iBuf[KMaxPkt];
    TPtr8 iPtr;
    TInetAddr iFrom;
};

static void RunL()
{
    CActiveScheduler* sch = new (ELeave) CActiveScheduler;
    CleanupStack::PushL(sch);
    CActiveScheduler::Install(sch);
    gRouter = new (ELeave) CRouter;
    CleanupStack::PushL(gRouter);
    gRouter->StartL();
    if (gRouter->CreateRouting()) {
        gRouter->ReportL(_L8("ready"));
        CActiveScheduler::Start();
    } else {
        gRouter->ReportL(_L8("unavailable"));
    }
    CleanupStack::PopAndDestroy(2);
    gRouter = NULL;
}

GLDEF_C TInt E32Main()
{
    CTrapCleanup* cleanup = CTrapCleanup::New();
    if (gFs.Connect() == KErrNone) {
        _LIT(KCard, "E:\\retrotele_btroute.txt");
        _LIT(KPhone, "C:\\Data\\retrotele_btroute.txt");
        TInt e = gLog.Open(gFs, KCard, EFileWrite | EFileShareAny);
        if (e != KErrNone) e = gLog.Replace(gFs, KCard, EFileWrite | EFileShareAny);
        if (e != KErrNone) { gFs.MkDirAll(KPhone); e = gLog.Replace(gFs, KPhone, EFileWrite | EFileShareAny); }
        if (e == KErrNone) { TInt pos = 0; gLog.Seek(ESeekEnd, pos); gLogOk = ETrue; }
    }
    Log(_L8("tgbtroute start"));
    TRAPD(err, RunL());
    Log(_L8("tgbtroute end %d"), err);
    if (gLogOk) gLog.Close();
    gFs.Close();
    delete cleanup;
    return err;
}
