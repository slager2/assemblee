"""Web image search + download with licence info, feeding the asset catalog.

    from assemblee.fetch import gather
    folder = gather("сделай ролик про семью", llm, "/tmp/family")   # -> Path, catalog cache pre-seeded
    cat = assets.load_or_build(folder, llm)                          # nothing is described twice

Providers (stdlib urllib, no API keys):
  openverse  https://api.openverse.org/v1/images/  anonymous: 20 req/min burst, 200 req/day, page_size <= 20
  wikimedia  Commons API, generator=search in the File namespace + imageinfo/extmetadata
  searxng    a local SearXNG (http://127.0.0.1:8081), opt-in, used only if reachable; licence "unknown"

Every kept file gets an entry in <dest>/credits.json (licence, author, attribution, source page) — use it
for the video's credits. Misfits rejected by the vision check are listed in <dest>/.rejected.json so a
rerun does not download them again.
"""
import io
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from . import assets

USER_AGENT = "assemblee/0.1 (local video editor; python-urllib)"
OPENVERSE = "https://api.openverse.org/v1/images/"
COMMONS = "https://commons.wikimedia.org/w/api.php"
SEARXNG = "http://127.0.0.1:8081"

MIN_SHORT_SIDE = 600
MAX_BYTES = 15 * 1024 * 1024
MAX_SIDE = 1920  # saved files are downscaled to this long side (vertical video is 1080x1920)
MIMES = {"image/jpeg", "image/png", "image/webp"}
EXT_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
DEFAULT_PROVIDERS = ("openverse", "wikimedia")
# licences that allow reuse with modification; NC/ND are excluded by the default Openverse filter
CLEAR_LICENSES = re.compile(r"^(cc[ -]?by(-sa)?|cc0|public domain|pdm|cc[ -]?pdm)", re.I)

_openverse_lock = threading.Lock()
_wikimedia_lock = threading.Lock()  # Wikimedia media servers answer 429 to parallel bursts: one at a time
_openverse_last = [0.0]


class FetchError(RuntimeError):
    pass


# ---------------------------------------------------------------- http

def _get(url, timeout=20, retries=2, max_bytes=None, accept="application/json"):
    """GET with retries (5xx, 429 with Retry-After, network errors). Returns (bytes, headers)."""
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                n = int(r.headers.get("Content-Length") or 0)
                if max_bytes and n > max_bytes:
                    raise FetchError(f"too large: {n} bytes")
                data = r.read(max_bytes + 1) if max_bytes else r.read()  # read(-1) leaks chunk framing
                if max_bytes and len(data) > max_bytes:
                    raise FetchError(f"too large: >{max_bytes} bytes")
                return data, r.headers
        except urllib.error.HTTPError as e:
            last = FetchError(f"HTTP {e.code} for {url[:120]}")
            if e.code == 429 or e.code >= 500:
                wait = e.headers.get("Retry-After") if e.headers else None
                try:
                    wait = min(float(wait), 10.0)
                except (TypeError, ValueError):
                    wait = 2.0 * (attempt + 1)
                if attempt < retries:
                    time.sleep(wait)
                    continue
            raise last from None
        except FetchError:
            raise
        except Exception as e:  # URLError, timeout, connection reset
            last = FetchError(f"{type(e).__name__}: {str(e)[:120]}")
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
    raise last


def _get_json(url, **kw):
    data, _ = _get(url, **kw)
    return json.loads(data)


def _strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = s.replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def url_key(url):
    """Same file under different hosts/thumb sizes (Openverse vs Commons thumbnails) -> one key."""
    name = urllib.parse.unquote(url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]).lower()
    if "wikimedia.org/" in url:
        return "wm:" + re.sub(r"^\d+px-", "", name)
    return url.split("?")[0]


def _result(**kw):
    keys = ("provider", "id", "title", "page_url", "image_url", "width", "height", "license", "license_url",
            "author", "attribution", "mime")
    r = {k: kw.get(k) for k in keys}
    r["license_clear"] = bool(r["license"] and CLEAR_LICENSES.match(r["license"]))
    return r


# ---------------------------------------------------------------- providers

def _commons_thumb(url, width, mime):
    """Commons originals are often 5-20 MB and upload.wikimedia.org throttles scripted clients hard (HTTP 429
    after a handful of files), while thumb.wikimedia.org serves the standard thumbnail buckets fine.
    Other bucket widths answer HTTP 400; a bucket wider than the file is served at the file's own size."""
    m = re.match(r"https://upload\.wikimedia\.org/wikipedia/commons/(?:thumb/)?(\w/\w\w)/([^/?]+)", url)
    if not m or mime == "image/webp":
        return url
    bucket = 1920 if (width or 0) > 1280 else 1280
    return f"https://thumb.wikimedia.org/wikipedia/commons/thumb/{m[1]}/{m[2]}/{bucket}px-{m[2]}"


def _openverse(query, n, orientation=None, license_type="commercial,modification", size="large"):
    """Anonymous Openverse: at most 20 per page, 20 requests/min, 200/day — spaced out by >= 3.1 s."""
    params = {"q": query, "page_size": min(20, max(1, n)), "mature": "false"}
    if license_type:
        params["license_type"] = license_type
    if size:
        params["size"] = size
    if orientation:
        params["aspect_ratio"] = {"vertical": "tall", "horizontal": "wide", "square": "square"}.get(orientation, orientation)
    with _openverse_lock:
        wait = _openverse_last[0] + 3.1 - time.time()
        if wait > 0:
            time.sleep(wait)
        _openverse_last[0] = time.time()
    d = _get_json(OPENVERSE + "?" + urllib.parse.urlencode(params))
    out = []
    for it in d.get("results", []):
        ft = (it.get("filetype") or "").lower()
        mime = EXT_MIME.get(ft) or EXT_MIME.get(it.get("url", "").rsplit(".", 1)[-1].lower().split("?")[0])
        lic, ver = (it.get("license") or "").lower(), it.get("license_version") or ""
        if lic in ("cc0",):
            name = f"CC0 {ver}".strip()
        elif lic == "pdm":
            name = "Public Domain Mark"
        else:
            name = f"CC {lic.upper()} {ver}".strip() if lic else ""
        url = it.get("url") or ""
        # Commons originals are often 5-20 MB; fetch a standard-bucket thumbnail instead
        url = _commons_thumb(url, it.get("width") or 0, mime)
        out.append(_result(provider="openverse", id=it.get("id"), title=it.get("title") or "",
                           page_url=it.get("foreign_landing_url"), image_url=url,
                           width=it.get("width"), height=it.get("height"), license=name,
                           license_url=it.get("license_url"), author=it.get("creator") or "",
                           attribution=it.get("attribution") or "", mime=mime,
                           source=it.get("source")))
    return out


def _wikimedia(query, n, orientation=None):
    params = {"action": "query", "format": "json", "formatversion": "2", "generator": "search",
              "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": "6", "gsrlimit": min(50, max(1, n)),
              "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "1600",
              "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|AttributionRequired|UsageTerms|ObjectName"}
    d = _get_json(COMMONS + "?" + urllib.parse.urlencode(params))
    pages = sorted(d.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        md = {k: (v or {}).get("value", "") for k, v in (ii.get("extmetadata") or {}).items()}
        w, hgt = ii.get("width") or 0, ii.get("height") or 0
        if orientation == "vertical" and hgt <= w or orientation == "horizontal" and w <= hgt:
            continue
        title = re.sub(r"^File:|\.\w+$", "", p.get("title", ""))
        author = _strip_html(md.get("Artist")) or _strip_html(md.get("Credit"))
        lic = _strip_html(md.get("LicenseShortName"))
        needs = md.get("AttributionRequired", "true") != "false"
        attribution = (f"\"{title}\" by {author or 'unknown author'}, {lic or 'see source'}, via Wikimedia Commons"
                       if needs else f"\"{title}\" ({lic}), via Wikimedia Commons")
        url = re.sub(r"\?utm_[^#]*$", "", ii.get("thumburl") or ii.get("url") or "")
        url = _commons_thumb(url, w, ii.get("mime"))  # small files: thumburl is the throttled original
        out.append(_result(provider="wikimedia", id=str(p.get("pageid")), title=title,
                           page_url=ii.get("descriptionurl"), image_url=url, width=w, height=hgt,
                           license=lic, license_url=md.get("LicenseUrl") or None, author=author,
                           attribution=attribution, mime=ii.get("mime"), attribution_required=needs))
    return out


def searxng_available(base=SEARXNG):
    try:
        _get(base.rstrip("/") + "/healthz", timeout=1.5, retries=0, accept="*/*")
        return True
    except Exception:
        return False


def _searxng(query, n, orientation=None, base=SEARXNG):
    if not searxng_available(base):
        return []
    d = _get_json(base.rstrip("/") + "/search?" + urllib.parse.urlencode(
        {"q": query, "categories": "images", "format": "json", "safesearch": 1}))
    out = []
    for it in d.get("results", [])[: n * 2]:
        m = re.match(r"(\d+)\s*[x×]\s*(\d+)", it.get("resolution") or "")
        w, hgt = (int(m[1]), int(m[2])) if m else (None, None)
        fmt = (it.get("img_format") or "").lower()
        mime = next((v for k, v in EXT_MIME.items() if k in fmt), None) if fmt else None
        src = it.get("img_src") or ""
        if src.startswith("//"):
            src = "https:" + src
        out.append(_result(provider="searxng", id=src, title=it.get("title") or "", page_url=it.get("url"),
                           image_url=src, width=w, height=hgt, license="unknown", license_url=None,
                           author=it.get("author") or it.get("engine") or "", mime=mime,
                           attribution=f"{it.get('title') or 'image'} — {it.get('url')} (licence unknown)"))
    return out


PROVIDERS = {"openverse": _openverse, "wikimedia": _wikimedia, "searxng": _searxng}


def search_images(query, n=10, orientation=None, providers=DEFAULT_PROVIDERS, on_error=None):
    """Searches the providers and returns up to n normalised results, interleaved provider by provider:
    {provider, id, title, page_url, image_url, width, height, license, license_url, author, attribution,
     mime, license_clear}. Filters: short side >= 600 px (when known), jpeg/png/webp, dedupe by URL.
    orientation: None | "vertical" | "horizontal" | "square"."""
    per = {}
    for name in providers:
        try:
            per[name] = PROVIDERS[name](query, max(n * 2, 10), orientation)
        except Exception as e:
            per[name] = []
            on_error and on_error(name, str(e))
    out, seen = [], set()
    queues = [list(v) for v in per.values()]
    while len(out) < n and any(queues):
        for q in queues:
            while q:
                r = q.pop(0)
                url = r["image_url"]
                if not url or url_key(url) in seen:
                    continue
                if r["mime"] and r["mime"] not in MIMES:
                    continue
                if r["width"] and r["height"] and min(r["width"], r["height"]) < MIN_SHORT_SIDE:
                    continue
                seen.add(url_key(url))
                out.append(r)
                break
            if len(out) >= n:
                break
    return out


# ---------------------------------------------------------------- download

def dhash(im, size=8):
    """64-bit difference hash; near-duplicates differ in a few bits."""
    g = im.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for y in range(size):
        for x in range(size):
            bits = bits << 1 | (px[y * (size + 1) + x] > px[y * (size + 1) + x + 1])
    return bits


def _hamming(a, b):
    return bin(a ^ b).count("1")


def slugify(s, maxlen=40):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:maxlen].rstrip("-") or "image")


def _credits_path(dest):
    return Path(dest) / "credits.json"


def load_credits(dest) -> dict:
    p = _credits_path(dest)
    return json.loads(p.read_text()) if p.exists() else {}


def _save_json(p, d):
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    tmp.replace(p)


def _load_rejected(dest) -> dict:
    p = Path(dest) / ".rejected.json"
    return json.loads(p.read_text()) if p.exists() else {}


def download(results, dest_dir, max_images=30, group="web", on_event=None, workers=4, timeout=30):
    """Downloads results into <dest>/<group>/<slug>.jpg (a result may carry its own "group").
    Size cap 15 MB, timeouts + retries, verified and re-encoded with Pillow (RGB JPEG, long side <= 1920),
    near-duplicates (dHash) dropped. Updates <dest>/credits.json keyed by asset id "<group>/<slug>".
    Returns the list of credit entries written (each with "asset_id", "path", all licence fields)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    credits = load_credits(dest)
    rejected = _load_rejected(dest)
    seen_urls = {url_key(c["image_url"]) for c in credits.values() if c.get("image_url")} | {url_key(u) for u in rejected}
    hashes = [int(c["dhash"], 16) for c in credits.values() if c.get("dhash")]
    todo = []
    for r in results:
        if url_key(r["image_url"]) not in seen_urls:
            seen_urls.add(url_key(r["image_url"]))
            todo.append(r)
    written, emit = [], (on_event or (lambda *a: None))
    stop = threading.Event()

    def one(r):
        if stop.is_set():
            return
        cid, t0 = uuid.uuid4().hex[:8], time.time()
        emit("tool_call", {"id": cid, "name": "download_image", "args": {"url": r["image_url"], "title": r["title"][:80]}})
        try:
            if "wikimedia.org/" in r["image_url"]:
                with _wikimedia_lock:
                    data, hdr = _get(r["image_url"], timeout=timeout, retries=1, max_bytes=MAX_BYTES, accept="image/*")
                    time.sleep(0.3)
            else:
                data, hdr = _get(r["image_url"], timeout=timeout, retries=2, max_bytes=MAX_BYTES, accept="image/*")
            ctype = (hdr.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and ctype.startswith("image/") and ctype not in MIMES:
                raise FetchError(f"mime {ctype}")
            im = Image.open(io.BytesIO(data))
            im.verify()
            im = Image.open(io.BytesIO(data))
            if im.format not in ("JPEG", "PNG", "WEBP", "MPO"):
                raise FetchError(f"format {im.format}")
            im.load()
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            if min(im.size) < MIN_SHORT_SIDE:
                raise FetchError(f"too small {im.size[0]}x{im.size[1]}")
            im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            dh = dhash(im)
            g = slugify(r.get("group") or group, 30).replace("-", "_")
            with lock:
                if stop.is_set():
                    return
                if any(_hamming(dh, x) <= 6 for x in hashes):
                    raise FetchError("near-duplicate of a downloaded image")
                base = slugify(r["title"])
                slug, k = base, 2
                while f"{g}/{slug}" in credits or (dest / g / f"{slug}.jpg").exists():
                    slug, k = f"{base}-{k}", k + 1
                (dest / g).mkdir(parents=True, exist_ok=True)
                path = dest / g / f"{slug}.jpg"
                im.save(path, "JPEG", quality=90, optimize=True)
                hashes.append(dh)
                entry = {k2: v for k2, v in r.items() if k2 != "group"}
                entry.update(asset_id=f"{g}/{slug}", group=g, path=str(path), file=f"{g}/{slug}.jpg",
                             saved_width=im.size[0], saved_height=im.size[1], dhash=f"{dh:016x}",
                             downloaded_at=round(time.time()))
                credits[entry["asset_id"]] = entry
                _save_json(_credits_path(dest), credits)
                written.append(entry)
                if len(written) >= max_images:
                    stop.set()
            emit("tool_result", {"id": cid, "name": "download_image", "ok": True, "seconds": round(time.time() - t0, 2),
                                 "result": {"asset_id": entry["asset_id"], "size": list(im.size), "license": r["license"]}})
        except Exception as e:
            emit("tool_result", {"id": cid, "name": "download_image", "ok": False, "seconds": round(time.time() - t0, 2),
                                 "result": {"error": str(e)[:200], "url": r["image_url"]}})

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))
    return written


# ---------------------------------------------------------------- gather (model-driven)

PLAN_SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "minItems": 2, "maxItems": 5, "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "snake_case English group name, e.g. family_dinner"},
            "shows": {"type": "string", "description": "what the picture must show"},
            "queries": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}}},
        "required": ["name", "shows", "queries"]}}},
    "required": ["groups"]}

CHECK_SCHEMA = {"type": "object", "properties": {"fits": {"type": "boolean"}, "what": {"type": "string"},
                                                 "mood": {"type": "string"}}, "required": ["fits", "what", "mood"]}

PLAN_PROMPT = """Ты подбираешь картинки для вертикального видеоролика. Задача пользователя:
«{task}»

Раздели нужные кадры на 2-5 смысловых групп (разные сцены ролика). Для каждой группы:
- name: короткое имя на английском в snake_case (например family_dinner, kids_playing);
- shows: что именно должно быть на картинке (по-русски, одна фраза);
- queries: 1-2 поисковых запроса НА АНГЛИЙСКОМ, 2-4 простых слова, как для фотостока
  (например "family dinner table", "grandparents with grandchildren"). Без кавычек и операторов.
Всего запросов 3-8. Ищем фотографии реальных сцен, не логотипы и не схемы."""

CHECK_PROMPT = """Картинка для видеоролика на тему «{task}». Нужна сцена: {shows}.
fits — подходит ли картинка для этой сцены (true/false; false для схем, текста, логотипов, карт, явно не той темы).
what — что изображено, по-русски, до 12 слов. mood — настроение, 1-3 слова по-русски."""


def plan_queries(task_text, llm):
    out, _ = llm.json([{"role": "user", "content": PLAN_PROMPT.format(task=task_text)}], PLAN_SCHEMA,
                      max_tokens=800, temperature=0.2)
    groups, total, names = [], 0, set()
    for g in out.get("groups", []):
        name = slugify(g.get("name") or "scene", 30).replace("-", "_")
        while name in names:
            name += "_2"
        qs = []
        for q in g.get("queries", []):
            q = re.sub(r"[^A-Za-z0-9 '\-]", " ", q)
            q = re.sub(r"\s+", " ", q).strip()
            if q and total < 8 and q.lower() not in {x.lower() for x in qs}:
                qs.append(q)
                total += 1
        if qs:
            names.add(name)
            groups.append({"name": name, "shows": (g.get("shows") or name).strip(), "queries": qs})
    if not groups:
        raise FetchError("the model returned no usable search queries")
    return groups


def _seed_catalog(dest, entries):
    """Writes the vision descriptions into the assets catalog cache in its own format (keyed by mtime)."""
    cp = assets.catalog_path(dest)
    cat = json.loads(cp.read_text()) if cp.exists() else {}
    for e in entries:
        p = Path(e["path"])
        if not p.exists():
            continue
        w, hgt = e["saved_width"], e["saved_height"]
        cat[e["asset_id"]] = {"path": str(p), "mtime": p.stat().st_mtime,
                              "orientation": "vertical" if hgt > w else "horizontal", "kind": "still",
                              "what": e["what"][:120], "mood": e["mood"][:40]}
    _save_json(cp, cat)
    return cp


def gather(task_text, llm, dest_dir, per_query=6, max_total=30, groups=None, orientation=None,
           providers=DEFAULT_PROVIDERS, check=True, on_event=None):
    """Task text (any language) -> folder of relevant, licence-tracked pictures ready for assets.load_or_build.
    groups: optional [{"name", "shows", "queries": [...]}] to skip the model's query planning.
    on_event(type, data) receives "tool_call"/"tool_result"/"warning" events shaped like docs/events.md."""
    dest = Path(dest_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    emit = on_event or (lambda *a: None)

    def step(name, args, fn):
        cid, t0 = uuid.uuid4().hex[:8], time.time()
        emit("tool_call", {"id": cid, "name": name, "args": args})
        try:
            res = fn()
        except Exception as e:
            emit("tool_result", {"id": cid, "name": name, "ok": False, "seconds": round(time.time() - t0, 2),
                                 "result": {"error": str(e)[:300]}})
            raise
        return res, (lambda summary: emit("tool_result", {"id": cid, "name": name, "ok": True,
                                                          "seconds": round(time.time() - t0, 2), "result": summary}))

    # (a) queries
    if groups is None:
        groups, done = step("plan_image_queries", {"task": task_text}, lambda: plan_queries(task_text, llm))
        done({"groups": groups})
    intents = {g["name"]: g["shows"] for g in groups}

    # (b) search + download
    n_queries = sum(len(g["queries"]) for g in groups)
    per_budget = max(1, min(per_query, -(-max_total // max(1, n_queries)) + 1))
    candidates = []
    for g in groups:
        for q in g["queries"]:
            res, done = step("search_images", {"query": q, "group": g["name"], "providers": list(providers)},
                             lambda: search_images(q, per_query * 2, orientation, providers,
                                                   on_error=lambda p, e: emit("warning", {"message": f"{p}: {e}"})))
            for r in res:
                r["group"], r["query"] = g["name"], q
            done({"count": len(res), "licensed": sum(r["license_clear"] for r in res),
                  "by_provider": {p: sum(r["provider"] == p for r in res) for p in providers}})
            candidates.append(res)
    # take per_budget per query first, then the rest as reserve (download stops at max_total)
    ordered, seen = [], set()
    for rank in range(2):
        for res in candidates:
            part = res[:per_budget] if rank == 0 else res[per_budget:per_query * 2]
            for r in part:
                if url_key(r["image_url"]) not in seen:
                    seen.add(url_key(r["image_url"]))
                    ordered.append(r)
    got, done = step("download_images", {"candidates": len(ordered), "max": max_total},
                     lambda: download(ordered, dest, max_total, on_event=on_event))
    done({"downloaded": len(got)})

    # (c) vision relevance check
    credits = load_credits(dest)
    fresh = [e for e in got if e["asset_id"] in credits]
    kept, dropped = [], []
    if check and llm is not None:
        lock = threading.Lock()
        rejected = _load_rejected(dest)

        def judge(e):
            cid, t0 = uuid.uuid4().hex[:8], time.time()
            emit("tool_call", {"id": cid, "name": "check_image", "args": {"asset_id": e["asset_id"], "shows": intents.get(e["group"], "")}})
            try:
                v = llm.vision(Path(e["path"]).read_bytes(),
                               CHECK_PROMPT.format(task=task_text, shows=intents.get(e["group"], e["group"])), CHECK_SCHEMA)
                ok = True
            except Exception as ex:  # keep the image, undescribed, if vision fails
                v, ok = {"fits": True, "what": e["title"][:120], "mood": f"(не описано: {str(ex)[:40]})"}, False
            e["what"], e["mood"], e["fits"] = (v.get("what") or "")[:120], (v.get("mood") or "")[:40], bool(v.get("fits"))
            with lock:
                if e["fits"]:
                    kept.append(e)
                    credits[e["asset_id"]].update(what=e["what"], mood=e["mood"], vision_checked=ok)
                else:
                    dropped.append(e)
                    Path(e["path"]).unlink(missing_ok=True)
                    credits.pop(e["asset_id"], None)
                    rejected[e["image_url"]] = {"asset_id": e["asset_id"], "title": e["title"], "what": e["what"],
                                                "mood": e["mood"], "group": e["group"]}
            emit("tool_result", {"id": cid, "name": "check_image", "ok": ok, "seconds": round(time.time() - t0, 2),
                                 "result": {"asset_id": e["asset_id"], "fits": e["fits"], "what": e["what"]}})

        with ThreadPoolExecutor(2) as ex:  # llama-server runs 2 slots
            list(ex.map(judge, fresh))
        _save_json(_credits_path(dest), credits)
        _save_json(dest / ".rejected.json", rejected)
        for g in {e["group"] for e in dropped}:
            d = dest / g
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        _seed_catalog(dest, kept)
    else:
        kept = fresh
    emit("tool_result", {"id": "gather", "name": "gather_images", "ok": True, "seconds": 0,
                         "result": {"dest": str(dest), "kept": len(kept), "rejected": len(dropped),
                                    "licensed": sum(credits[e["asset_id"]]["license_clear"] for e in kept)}})
    return dest
