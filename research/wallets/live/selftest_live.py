"""Selftest of research/wallets/live/recorder.py with made-up events and a made-up clock (no network)."""
import os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recorder as R

MINT = R.b58dec("ERRZ89iFpMnCoQgDwVmVTbpLw36czDXdKbS9C5w9pump")
POOL = bytes(range(1, 33)); OTHER = bytes(range(2, 34))
T0 = 1_800_000_000


def create(t, pool, mint=MINT):
    return R.D_CREATE + t.to_bytes(8, "little") + b"\0" * 2 + b"\7" * 32 + mint + R.WSOL + b"\0" * 60 + pool + b"\0" * 64


def trade(kind, t, pool, user, sol, price):
    base = 200_000_000 * 10 ** 6
    quote = int(price * (base / 1e6) * 1e9)
    b = bytearray(300)
    b[0:8] = R.D_BUY if kind == "b" else R.D_SELL
    b[8:16] = t.to_bytes(8, "little"); b[48:56] = base.to_bytes(8, "little"); b[56:64] = quote.to_bytes(8, "little")
    b[64:72] = int(sol * 1e9).to_bytes(8, "little"); b[120:152] = pool; b[152:184] = user
    return bytes(b)


def w(i):
    return bytes([i]) * 32


def main():
    assert R.PREFIX.get("Z/RSHyz1d3") == "b" and R.PREFIX.get("Pi83CqUD3C") == "s", R.PREFIX      # the prefixes seen on the chain
    assert R.exit_a([1.0, 0.9, 0.6], [1.0, 0.9, 0.6], [1.0, 0.9, 0.6], 1.0) == (0.6, "stop")
    assert R.exit_a([2, 12], [2, 12], [2, 12], 1.0) == (11.0, "target")
    assert R.exit_a([float("nan"), 1.2], [float("nan"), 1.2], [float("nan"), 1.2], 1.0) == (1.2, "time")
    assert R.exit_a([5.0], [0.5], [12.0], 1.0) == (0.5, "stop")                                   # both in one minute: the stop
    f, j = R.money(2.0)
    v = 40 * 0.99 / 1.01
    assert abs(f - (v - 20 - 0.4 - 0.02 * v)) < 1e-3 and abs(j - (v - 20 - 0.1)) < 1e-3
    # the list: wallet 1 has 12 good copies, wallet 2 has 12 bad ones, wallet 3 only 5 good ones
    day = T0 // R.DAY
    pb = {day - 5: dict(w=np.array([1] * 12 + [2] * 12 + [3] * 5, np.uint64),
                        a=np.array([1.5, 1.6, 1.4, 1.7] * 3 + [0.7] * 12 + [3.0] * 5, np.float32)),
          day - 1: dict(w=np.array([2] * 20, np.uint64), a=np.array([9.0] * 20, np.float32)),      # inside the lag: not used
          day - 30: dict(w=np.array([2] * 20, np.uint64), a=np.array([9.0] * 20, np.float32))}     # too old
    L, nd = R.build_list(pb, day)
    assert set(L) == {1} and nd == 1 and L[1][0] == 12, (L, nd)

    with tempfile.TemporaryDirectory() as tmp:
        rec = R.Recorder(tmp)
        rec.list_day = day; rec.list = {R.h64(w(9)): (12, 0.5, 3.0)}; rec.list_days = 21
        t = T0
        rec.on_event("b", trade("b", t, POOL, w(5), 1.0, 1e-6), t)            # before any create event: this pool is ignored
        assert POOL in rec.ignored and not rec.pending
        rec.ignored.clear()
        rec.on_event("c", create(t, POOL), t)
        rec.on_event("c", create(t, OTHER, mint=b"\5" * 32), t)               # not a pump.fun coin
        rec.on_event("b", trade("b", t + 1, OTHER, w(5), 1.0, 1e-6), t + 1)
        assert OTHER in rec.ignored
        rec.on_event("b", trade("b", t + 10, POOL, w(5), 0.05, 1.0e-6), t + 10)     # too small
        rec.on_event("b", trade("b", t + 20, POOL, w(5), 0.5, 1.0e-6), t + 20)      # a pair
        rec.on_event("b", trade("b", t + 25, POOL, w(5), 0.5, 1.1e-6), t + 25)      # the same wallet again: no new pair
        rec.on_event("b", trade("b", t + 30, POOL, w(9), 0.2, 1.2e-6), t + 30)      # the listed wallet: a pair and a paper buy
        assert len(rec.pending) == 2 and len(rec.waiting) == 1
        rec.on_event("s", trade("s", t + 80, POOL, w(7), 0.3, 2.0e-6), t + 80)      # the price one minute after wallet 5 and 9: 2.0e-6
        rec.on_event("b", trade("b", t + 200, POOL, w(8), 0.01, 2.4e-6), t + 200)
        rec.tick(t + 100)
        assert len(rec.open) == 1 and abs(rec.open[0]["entry"] - 2.0e-6) < 1e-12 and not rec.open[0]["warm"], rec.open
        rec.on_event("s", trade("s", t + 1000, POOL, w(7), 0.3, 1.3e-6), t + 1000)  # under -30% from 2.0e-6: the stop
        rec.tick(t + 1100)
        assert not rec.open and len(rec.closed) == 1 and rec.closed[0]["how"] == "stop" and abs(rec.closed[0]["mult"] - 0.65) < 1e-6, rec.closed
        rec.on_event("b", trade("b", t + 2000, POOL, w(9), 0.2, 1.2e-6), t + 2000)  # the coin was copied once: not again
        assert not rec.waiting
        rec.tick(t + 30 + 60 + 360 * 60 + 100)
        d = rec.pairs[t // R.DAY]
        assert len(d["w"]) == 2 and not rec.pending and all(abs(x - 0.65) < 1e-6 for x in d["a"]), d
        rec.save()
        rec2 = R.Recorder(tmp)
        assert len(rec2.pairs[t // R.DAY]["w"]) == 2 and len(rec2.closed) == 1 and (R.h64(w(5)), R.h64(POOL)) in rec2.seen
    print("selftest_live ok")


if __name__ == "__main__":
    main()
