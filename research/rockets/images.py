"""Rocket study (fake money only; research/rockets/PREREG-ROCKETS-2026-10-24.md, amendment 5): what each coin's picture shows,
read by OpenAI's CLIP model (openai/clip-vit-base-patch32) on GitHub's machines.

  shard <chain.parquet> <i> <n> <out.parquet> [<thumb dir>]   coins i, i+n, ... of those whose metadata file names a picture
  final <dir with shard files> <out dir>                       one images.parquet (+ the thumbnails of the hand check)

Per picture: the file type, whether it is animated (a GIF with more than one frame), a 64-bit average hash (look-alikes), CLIP's
scores for six fixed descriptions (GROUPS) and the best one, and how CLIP ranks the coin's own name against 20 other coins' names
for this picture (name_fit, 0 = worst, 1 = best). The 120 coins of the hand check (SAMPLE: drawn at random with seed 7 from all
coins with a picture, no outcome used) are also saved as small numbered pictures without their names, for sorting by hand.
Nothing is bought; no key is used."""
import concurrent.futures, glob, io, json, os, re, sys, threading, time, urllib.error, urllib.request

GROUPS = {"animal_photo": "a photo of a real animal", "animal_drawn": "a cartoon drawing of an animal",
          "person_photo": "a photo of a real person", "character_drawn": "a cartoon drawing of a person or character",
          "text_logo": "a logo or text or symbol", "object_scene": "a photo of an object or a place"}
GATEWAYS = ("https://ipfs.io/ipfs/%s", "https://gateway.pinata.cloud/ipfs/%s", "https://dweb.link/ipfs/%s", "https://w3s.link/ipfs/%s",
            "https://4everland.io/ipfs/%s", "https://nftstorage.link/ipfs/%s", "https://ipfs.filebase.io/ipfs/%s")
CID = re.compile(r"/ipfs/([A-Za-z0-9]{20,})")
UA = {"User-Agent": "memebot-research (github.com/maxpandelakis-boop/Meme-Bot)"}
MAX_BYTES = 4_000_000
SAMPLE_N, SEED = 120, 7


def log(*a):
    print(*a, flush=True)


_locks, _last, _g = {}, {}, threading.Lock()
_k = [0]


def fetch(url, gap=0.3, timeout=15):
    host = url.split("/")[2]
    with _g:
        lk = _locks.setdefault(host, threading.Lock())
    with lk:
        w = _last.get(host, 0) + gap - time.time()
        if w > 0:
            time.sleep(w)
        _last[host] = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            b = r.read(MAX_BYTES + 1)
            return (b if len(b) <= MAX_BYTES else None), ("ok" if len(b) <= MAX_BYTES else "big")
    except urllib.error.HTTPError as e:
        return None, str(e.code)
    except Exception as e:
        return None, type(e).__name__


def picture(url):
    m = CID.search(url or "")
    if m:
        with _g:
            k = _k[0]
            _k[0] += 1
        urls = [GATEWAYS[(k + j) % len(GATEWAYS)] % m.group(1) for j in range(3)]
    else:
        urls = [url] if (url or "").startswith("http") else []
    st = "nourl"
    for u in urls:
        b, st = fetch(u, gap=float(os.environ.get("GW_GAP") or 0.3))
        if b:
            return b, "ok"
    return None, st


def ahash(img):
    g = img.convert("L").resize((8, 8))
    px = list(g.getdata())
    mean = sum(px) / 64
    v = 0
    for p in px:
        v = (v << 1) | (1 if p > mean else 0)
    return "%016x" % v


def with_picture(d):
    """Rows whose metadata file names a picture (meta_chain.py final of 24 Oct wrote missing values as the text "NaN")."""
    x = d["f_image"].fillna("").astype(str).str.strip()
    return d[(x.str.len() > 0) & ~x.isin(["NaN", "None", "null"])]


def sample_mints(chain_path):
    import pandas as pd, numpy as np
    d = with_picture(pd.read_parquet(chain_path)).sort_values("mint")
    rng = np.random.default_rng(SEED)
    return list(d["mint"].to_numpy()[rng.choice(len(d), size=min(SAMPLE_N, len(d)), replace=False)])


def cmd_shard(chain_path, i, n, out, thumbs=None):
    import numpy as np, pandas as pd, torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor
    torch.set_num_threads(os.cpu_count() or 2)
    d = with_picture(pd.read_parquet(chain_path)).sort_values("mint").reset_index(drop=True)
    nm = d["f_name"].fillna(d["name"]) if "name" in d else d["f_name"]
    d["f_name"] = nm
    names_all = nm.fillna("").astype(str).tolist()
    part = d.iloc[int(i)::int(n)].reset_index(drop=True)
    sample = {m: k for k, m in enumerate(sample_mints(chain_path))}
    if thumbs:
        os.makedirs(thumbs, exist_ok=True)
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").eval()
    proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    with torch.no_grad():
        t = proc(text=list(GROUPS.values()), return_tensors="pt", padding=True)
        tg = model.get_text_features(**t)
        tg = tg / tg.norm(dim=-1, keepdim=True)
    stop = time.time() + 60 * float(os.environ.get("SHARD_MINUTES", 150))
    rng = np.random.default_rng(int(i) + 1000)
    pool = concurrent.futures.ThreadPoolExecutor(int(os.environ.get("WORKERS") or 16))
    rows, codes = [], {}
    B = 64
    for a in range(0, len(part), B):
        if time.time() > stop:
            log("time budget used at", a, "of", len(part))
            break
        chunk = part.iloc[a:a + B]
        got = list(pool.map(picture, chunk["f_image"].astype(str)))
        imgs, recs = [], []
        for (_, r), (b, st) in zip(chunk.iterrows(), got):
            rec = {"mint": r["mint"], "img_ok": False, "status": st}
            codes[st] = codes.get(st, 0) + 1
            if b:
                try:
                    im = Image.open(io.BytesIO(b))
                    rec["fmt"] = im.format
                    rec["animated"] = bool(getattr(im, "n_frames", 1) > 1)
                    im.seek(0)
                    rgb = im.convert("RGB")
                    rec["ahash"] = ahash(rgb)
                    rec["bytes"] = len(b)
                    rec["img_ok"] = True
                    imgs.append(rgb)
                    if thumbs and r["mint"] in sample:
                        th = rgb.copy()
                        th.thumbnail((160, 160))
                        th.save(os.path.join(thumbs, "%03d.jpg" % sample[r["mint"]]), quality=85)
                except Exception as e:
                    rec["status"] = "bad:" + type(e).__name__
            recs.append(rec)
        okr = [r for r in recs if r["img_ok"]]
        if imgs:
            own = [str(x) for x in chunk.loc[[r["img_ok"] for r in recs], "f_name"].fillna("").astype(str)]
            others = [[names_all[k] for k in rng.choice(len(names_all), 20)] for _ in imgs]
            with torch.no_grad():
                px = proc(images=imgs, return_tensors="pt")
                fi = model.get_image_features(**px)
                fi = fi / fi.norm(dim=-1, keepdim=True)
                pr = (100 * fi @ tg.T).softmax(dim=-1).numpy()
                texts = []
                for o, oth in zip(own, others):
                    texts += ["a picture of " + (o or "nothing")[:60]] + ["a picture of " + (x or "nothing")[:60] for x in oth]
                tt = proc(text=texts, return_tensors="pt", padding=True, truncation=True, max_length=40)
                fn = model.get_text_features(**tt)
                fn = (fn / fn.norm(dim=-1, keepdim=True)).reshape(len(imgs), 21, -1)
                sims = torch.einsum("bd,bkd->bk", fi, fn).numpy()
            for r, p, s in zip(okr, pr, sims):
                for g, v in zip(GROUPS, p):
                    r["p_" + g] = float(v)
                r["group"] = list(GROUPS)[int(np.argmax(p))]
                r["name_fit"] = float((s[1:] < s[0]).mean())
        rows += recs
        if a % (B * 16) == 0:
            log(a + len(chunk), "of", len(part), "pictures", sum(r["img_ok"] for r in rows), codes)
            pd.DataFrame(rows).to_parquet(out, index=False)
    pool.shutdown()
    pd.DataFrame(rows).to_parquet(out, index=False)
    log("done", len(rows), "pictures", sum(r["img_ok"] for r in rows), codes)


def cmd_final(src, out):
    import pandas as pd, shutil
    os.makedirs(out, exist_ok=True)
    fs = sorted(glob.glob(os.path.join(src, "**", "img_*.parquet"), recursive=True))
    d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True).drop_duplicates("mint")
    d.to_parquet(os.path.join(out, "images.parquet"), index=False)
    th = sorted(glob.glob(os.path.join(src, "**", "thumbs", "*.jpg"), recursive=True))
    os.makedirs(os.path.join(out, "handcheck"), exist_ok=True)
    for f in th:
        shutil.copy(f, os.path.join(out, "handcheck", os.path.basename(f)))
    log("pictures", int(d["img_ok"].sum()), "of", len(d), "groups", d["group"].value_counts().to_dict() if "group" in d else {},
        "hand-check pictures", len(th))


if __name__ == "__main__":
    {"shard": cmd_shard, "final": cmd_final}[sys.argv[1]](*sys.argv[2:])
