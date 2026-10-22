#!/usr/bin/env python3
"""daily.py: the evening report ("Tagesbericht") as one push notification to the iPhone app. Fake money only: nothing here buys, signs
or sends anything but the notification, and nothing in it is advice. German words, like the user writes.

daily.yml runs it at 19:00 and 20:00 UTC; it sends at the first run whose Berlin time is from SEND_FROM_H on (21:xx in summer and in
winter), once per Berlin day: the live store's row "daily" keeps the day it last went out (read before, written after), so a second
run that evening, a late cron start or a run by hand ("send") never sends it twice. The phones' own switch "Tagesbericht" (prefs
"daily", app.wants) decides whether a phone gets it.

What it says (words(): a title and one body within app.TITLE_MAX and app.BODY_MAX, never buy, safe or clean):
  - Pick: today's buys, the buys sold today and what they made, the open positions, the account since its restart (closed results
    plus the open positions at their last price, the paper fees included)
  - Radar (the rocket hunter, rocket.json from the branch rocket-data): the same four numbers
  - the shadow rules (shadow.summary): which one is ahead of the real rule replayed, on how many buys
  - the nightly filter search (filtersearch.json from the branch filtersearch): a rule that beat the gates on unseen coins, or not
"Today" is the Berlin day up to now. Each part says "–" when its doc is missing; a missing doc never stops the report.

Usage:
  python3 daily.py run --dir mb [--rocket rocket.json] [--fs filtersearch.json] [--now ms] [--mode auto|send|dry]
      auto: send when it is time and not sent today; send: now (still once a day); dry: print the words only, send nothing
      -> one JSON line; exit 0 always
"""
import argparse, datetime as dt, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import memebot as M      # read only: positions, in_account, pos_value

SEND_FROM_H = 21          # Berlin hour from which the report goes out (the user: about 21:00 German time)
ROW = "daily"             # the live store's row that keeps the last day sent
MINUS = "−"


def num(v):
    return M.num(v)


def berlin(ms):
    """A moment (ms) as Berlin time: zoneinfo when the machine has it, else the EU summer-time rule (the scan's own fallback)."""
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        last_sun = lambda y, m: max(x for x in (dt.datetime(y, m, d_, 1, tzinfo=dt.timezone.utc) for d_ in range(25, 32)) if x.weekday() == 6)
        off = 2 if last_sun(t.year, 3) <= t < last_sun(t.year, 10) else 1
        return (t + dt.timedelta(hours=off)).replace(tzinfo=dt.timezone(dt.timedelta(hours=off)))


def day_start(now):
    """The Berlin midnight before now, in ms."""
    b = berlin(now)
    return int((b.replace(hour=0, minute=0, second=0, microsecond=0)).timestamp() * 1000)


def eur(v, signed=True):
    """+12,30 € / −8,05 € / 0,00 € (German, a real minus)."""
    v = num(v) or 0.0
    s = format(abs(v), ",.2f").replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    sign = MINUS if v < -0.004 else ("+" if signed and v > 0.004 else "")
    return "%s%s €" % (sign, s)


def load(path):
    doc = M.load_json(path, None) if path else None
    return doc if isinstance(doc, dict) else None


# ---------------------------------------------------------------- the numbers
def pick_day(d, now, pos=None):
    """The Pick account (grp "hold", since the restart) today: buys, the buys sold today and their result, open positions, and the
    account's balance (closed results plus the open ones at their last marked price, after the paper fees)."""
    pos = M.positions(d) if pos is None else pos
    state = M.load_json(os.path.join(d, "db", "memebot", "state.json"), {}) or {}
    since = num(state.get("paperSince")) if isinstance(state, dict) else None
    marks = M.load_json(os.path.join(d, "db", "memebot", "marks.json"), {}) or {}
    px = marks.get("px") if isinstance(marks, dict) and isinstance(marks.get("px"), dict) else {}
    start = day_start(now)
    buys = sold = n_open = 0
    sold_eur = bal = 0.0
    for pid, p in pos.items():
        if not isinstance(p, dict) or p.get("grp") != "hold" or not M.in_account(p, since):
            continue
        ticket = num(p.get("ticket")) or 0.0
        exits = [e for e in p.get("_exits") or [] if isinstance(e, dict)]
        back = sum(num(e.get("eur")) or 0.0 for e in exits)
        left = num(p.get("_left")) or 0.0
        if (num(p.get("t")) or 0) >= start:
            buys += 1
        if left > 1e-9:
            n_open += 1
            entry, last = num(p.get("px")), num(px.get(pid))
            bal += back + (M.pos_value(p, left, last / entry) if entry and last else 0.0) - ticket
        else:
            bal += back - ticket
            if exits and (num(exits[-1].get("t")) or 0) >= start:
                sold += 1
                sold_eur += back - ticket
    return {"buys": buys, "sold": sold, "soldEur": round(sold_eur, 2), "open": n_open, "bal": round(bal, 2)}


def rocket_day(doc, now):
    """The rocket hunter's account (rocket.json's book) today: the same numbers; None without a readable doc."""
    bk = doc.get("book") if isinstance(doc, dict) and isinstance(doc.get("book"), dict) else None
    if bk is None:
        return None
    start = day_start(now)
    opn = [p for p in (bk.get("open") or {}).values() if isinstance(p, dict)] if isinstance(bk.get("open"), dict) else []
    closed = [p for p in bk.get("closed") or [] if isinstance(p, dict)]
    sm = bk.get("summary") if isinstance(bk.get("summary"), dict) else {}
    today = [p for p in closed if (num(p.get("out")) or 0) >= start]
    return {"buys": sum(1 for p in opn + closed if (num(p.get("t")) or 0) >= start), "sold": len(today),
            "soldEur": round(sum(num(p.get("eur")) or 0.0 for p in today), 2), "open": len(opn),
            "bal": round((num(sm.get("eur")) or 0.0) + (num(sm.get("openEur")) or 0.0), 2)}


def shadow_line(d, now):
    try:
        import shadow as SH
        S = SH.summary(d, now)
    except Exception:
        return ""
    if not S["n"]:
        return "Schatten-Regeln: noch kein Kauf ausgewertet (%d läuft)" % S["open"] if S["open"] else "Schatten-Regeln: noch kein Kauf"
    k = next(a for a in S["accts"] if a["id"] == "K")
    lead = next((a for a in S["accts"] if a["id"] == S["leader"]), None)
    if not lead:
        return ""
    if not S["ahead"]:
        return "Schatten (%d Käufe): keine Regel besser als die echte" % S["n"]
    return "Schatten (%d Käufe): vorn %s %s, %s gegen die echte Regel" % (S["n"], lead["id"], lead["name"], eur(lead["eur"] - k["eur"]))


def filter_line(doc, now):
    if not isinstance(doc, dict) or not isinstance(doc.get("data"), dict):
        return "Filtersuche: kein Ergebnis"
    t = num(doc.get("t")) or 0
    old = " (von %s)" % berlin(t).strftime("%d.%m.") if t and now - t > 36 * 3_600_000 else ""
    if isinstance(doc.get("leader"), dict):
        return "Filtersuche%s: eine Regel schlägt die Gates bei neuen Coins (nicht eingeschaltet, deine Entscheidung)" % old
    return "Filtersuche%s: noch keine Regel besser als die Gates" % old


def words(d, now, rocket=None, fs=None):
    """(title, body) of the evening report."""
    import app as A
    pk, rk = pick_day(d, now), rocket_day(rocket, now)

    def part(name, x):
        if x is None:
            return "%s: –" % name
        return "%s: %d %s, %d verkauft (%s), %d offen, Konto %s" % (
            name, x["buys"], "Kauf" if x["buys"] == 1 else "Käufe", x["sold"], eur(x["soldEur"]), x["open"], eur(x["bal"]))
    today = lambda x: eur(x["soldEur"]) if x is not None else "–"
    title = "Tagesbericht %s: Pick %s, Radar %s" % (berlin(now).strftime("%d.%m."), today(pk), today(rk))
    tail = "Nur Papiergeld."
    bits = [part("Pick", pk), part("Radar", rk), shadow_line(d, now), filter_line(fs, now)]
    bits = [b for b in bits if b]
    while bits:
        body = " · ".join(bits) + ". " + tail
        if len(body) <= A.BODY_MAX:
            break
        bits.pop()                             # the last part goes first: the two accounts stay
    else:
        body = tail
    return title[:A.TITLE_MAX], body


# ---------------------------------------------------------------- sending
def time_to_send(now):
    return berlin(now).hour >= SEND_FROM_H


def sent_day():
    """The Berlin day the report last went out (the live store's row "daily"), "" for none, None when the store did not answer."""
    import app as A
    try:
        rows = A.call("GET", "live?select=doc&id=eq.%s" % ROW)
    except Exception:
        return None
    doc = rows[0].get("doc") if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    return str(doc.get("day") or "") if isinstance(doc, dict) else ""


def run(d, now, rocket_path=None, fs_path=None, mode="auto"):
    """-> the summary line (dict). Never raises."""
    out = {"ok": True, "mode": mode, "sent": False}
    try:
        day = berlin(now).strftime("%Y-%m-%d")
        title, body = words(d, now, load(rocket_path), load(fs_path))
        out.update(day=day, title=title, body=body)
        if mode == "dry":
            out["why"] = "dry run: nothing sent"
            return out
        if mode == "auto" and not time_to_send(now):
            out["why"] = "before %d:00 Berlin" % SEND_FROM_H
            return out
        import app as A
        if not A.enabled():
            out["why"] = "no live store (the Supabase secrets are not set)"
            return out
        last = sent_day()
        if last is None:
            out["why"] = "the live store did not answer: not sent (never twice)"
            return out
        if last == day:
            out["why"] = "already sent today"
            return out
        res = A.notify_daily(title, body)
        out["push"] = res
        if res.get("skipped"):
            out["why"] = "not sent: %s" % res["skipped"]
            return out
        out["sent"] = True
        try:
            A.put_row(ROW, {"day": day, "t": int(now), "title": title, "body": body, "sentTo": res.get("sent", 0)})
        except Exception as e:
            out["mark"] = "not written (%s): a second run today could send it again" % type(e).__name__
        out["why"] = "sent to %d phone%s" % (res.get("sent", 0), "" if res.get("sent", 0) == 1 else "s")
    except Exception as e:
        out.update(ok=False, err="%s: %s" % (type(e).__name__, str(e)[:200]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="the evening report as one push notification (fake money only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dir", default="mb")
    r.add_argument("--rocket", default=None, help="rocket.json (branch rocket-data)")
    r.add_argument("--fs", default=None, help="filtersearch.json (branch filtersearch)")
    r.add_argument("--now", type=int, default=None, help="ms; default: the wall clock")
    r.add_argument("--mode", choices=("auto", "send", "dry"), default="auto")
    a = ap.parse_args(argv)
    now = a.now if a.now is not None else int(time.time() * 1000)
    print(json.dumps(run(a.dir, now, a.rocket, a.fs, a.mode), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
