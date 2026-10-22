"""Winner/loser study, social probe (fake money only): for a sample of history2 coins (social_coins.csv: winners, losers, others
at their first entry hour), how much did people talk about them BEFORE that hour? pump.fun replies (timestamps) and Reddit
search (RSS, by the coin's address and by $SYMBOL). Runs in GitHub Actions (the cloud session cannot reach these hosts).
usage: python3 research/winlose/social_probe.py social_coins.csv out.jsonl"""
import csv, json, re, sys, time, urllib.parse, urllib.request
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (memebot research; fake money only)"}
PF = "https://frontend-api-v3.pump.fun"


def get(url, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(15 * (k + 1)); continue
            return e.code, b""
        except Exception as e:
            time.sleep(3)
    return -1, b""


def pf_replies(mint):
    out, off = [], 0
    while off < 3000:
        st, b = get(PF + "/replies/%s?limit=1000&offset=%d&reverseOrder=false" % (mint, off))
        time.sleep(0.7)
        if st != 200:
            return st, out
        data = json.loads(b or b"null")
        items = data.get("replies") if isinstance(data, dict) else data
        if not items:
            break
        for it in items:
            ts = it.get("timestamp")
            if ts:
                out.append([ts / 1000.0 if ts > 1e11 else ts, str(it.get("user") or "")])
        if len(items) < 1000:
            break
        off += 1000
    return 200, out


def rss(q):
    st, b = get("https://www.reddit.com/search.rss?" + urllib.parse.urlencode({"q": q, "sort": "new", "limit": 100}))
    time.sleep(7)
    if st != 200:
        return st, []
    times = [m for m in re.findall(rb"<published>([^<]+)</published>", b)] or re.findall(rb"<updated>([^<]+)</updated>", b)[1:]
    from datetime import datetime
    out = []
    for t in times:
        try:
            out.append(datetime.fromisoformat(t.decode().replace("Z", "+00:00")).timestamp())
        except Exception:
            pass
    return st, out


def main():
    rows = list(csv.DictReader(open(sys.argv[1])))
    with open(sys.argv[2], "w") as f:
        for i, r in enumerate(rows):
            rec = {"mint": r["mint"], "label": r["label"], "ts": int(r["ts"]), "grad_ms": int(r["grad_ms"])}
            rec["pf_status"], rec["pf"] = pf_replies(r["mint"])
            rec["rd_mint_status"], rec["rd_mint"] = rss('"%s"' % r["mint"])
            sym = (r.get("symbol") or "").strip().lstrip("$")
            if sym and len(sym) >= 3:
                rec["rd_sym_status"], rec["rd_sym"] = rss('"$%s" solana' % sym)
            f.write(json.dumps(rec) + "\n"); f.flush()
            if i % 25 == 0:
                print(i, r["label"], rec["pf_status"], len(rec["pf"]), rec["rd_mint_status"], len(rec["rd_mint"]), rec.get("rd_sym_status"), len(rec.get("rd_sym", [])), flush=True)


if __name__ == "__main__":
    main()
