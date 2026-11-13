"""Real music for the edit: CC/PD search + download with licences, tempo/beat/drop analysis, beat-snapping.

    from assemblee.music import gather_music, beat_snap
    lib = gather_music("ролик про семью", llm, "/tmp/family", ["warm", "dark_retro_horror"])
    edl.music_library = {t["id"]: t for t in lib}          # Section.music may now be a track id
    sec.music, sec.music_start = lib[0]["id"], None          # None -> the track's best_start (the drop)

Providers (stdlib urllib, no API keys; same User-Agent and retry helper as fetch.py):
  openverse  https://api.openverse.org/v1/audio/  category=music, license_type=commercial,modification
             (mostly Jamendo tracks, CC BY / BY-SA); anonymous budget shared with the image search
  ccmixter   https://ccmixter.org/api/query  (public query API, f=json); NC / sampling licences dropped
  wikimedia  Commons API, File namespace, filetype:audio + videoinfo (duration, licence, mp3 derivative)

Every kept track is converted to 48 kHz stereo wav (ffmpeg loudnorm I=-16) at <dest>/music/<slug>.wav and
gets an entry (kind "music") in <dest>/credits.json, the same file the picture search writes.
Analysis (no LLM, no numpy) needs only ffmpeg: band energy envelopes at 100 frames/s -> onset strength ->
autocorrelation tempo -> dynamic-programming beat tracker (Ellis 2007) -> loudest 10 s window = the drop.
"""
import bisect
import http.client
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import uuid
from array import array
from pathlib import Path

from .fetch import (CLEAR_LICENSES, COMMONS, FetchError, _get, _get_json, _openverse_last, _openverse_lock,
                    _save_json, _strip_html, _wikimedia_lock, load_credits, slugify)

OPENVERSE_AUDIO = "https://api.openverse.org/v1/audio/"
CCMIXTER = "https://ccmixter.org/api/query"
DEFAULT_PROVIDERS = ("openverse", "ccmixter", "wikimedia")
MIN_SECONDS, MAX_SECONDS = 30, 300
MAX_BYTES = 40 * 1024 * 1024  # a 5 min 320 kbps mp3 is ~12 MB; Commons originals (wav/flac) can be larger
KEEP_SECONDS = 300  # converted wavs are cut to this length
FRAME_RATE = 100  # analysis frames per second
DROP_WINDOW = 10.0


# ---------------------------------------------------------------- search

def _result(**kw):
    keys = ("provider", "id", "title", "artist", "duration", "tags", "license", "license_url", "page_url",
            "audio_url", "attribution", "instrumental", "bpm_hint")
    r = {k: kw.get(k) for k in keys}
    r["tags"] = [t for t in (r["tags"] or []) if t][:20]
    r["license_clear"] = bool(r["license"] and CLEAR_LICENSES.match(r["license"]))
    return r


def _cc_name(code, version=""):
    code = (code or "").lower()
    if code == "cc0":
        return f"CC0 {version}".strip()
    if code == "pdm":
        return "Public Domain Mark"
    return f"CC {code.upper()} {version}".strip() if code else ""


def _openverse(query, n, min_s=MIN_SECONDS, max_s=MAX_SECONDS):
    """Anonymous Openverse: page_size <= 20, ~20 requests/min, 200/day; duration comes in milliseconds."""
    params = {"q": query, "page_size": min(20, max(1, n)), "category": "music", "mature": "false",
              "license_type": "commercial,modification"}
    with _openverse_lock:
        wait = _openverse_last[0] + 3.1 - time.time()
        if wait > 0:
            time.sleep(wait)
        _openverse_last[0] = time.time()
    d = _get_json(OPENVERSE_AUDIO + "?" + urllib.parse.urlencode(params))
    out = []
    for it in d.get("results", []):
        dur = (it.get("duration") or 0) / 1000
        if not min_s <= dur <= max_s or not it.get("url"):
            continue
        tags = [t.get("name") for t in it.get("tags") or [] if isinstance(t, dict)]
        genres = [g for g in it.get("genres") or [] if g]
        instr = True if "instrumental" in tags else False if "vocal" in tags else None
        out.append(_result(provider="openverse", id=it.get("id"), title=re.sub(r"\s*\((mp3|ogg)\)$", "", it.get("title") or ""),
                           artist=it.get("creator") or "", duration=round(dur, 1), tags=genres + tags,
                           license=_cc_name(it.get("license"), it.get("license_version") or ""),
                           license_url=it.get("license_url"), page_url=it.get("foreign_landing_url"),
                           audio_url=it["url"], attribution=it.get("attribution") or "", instrumental=instr))
    return out


def _parse_mmss(s):
    m = re.match(r"^(?:(\d+):)?(\d+):(\d+)$", str(s or "").strip())
    return int(m[1] or 0) * 3600 + int(m[2]) * 60 + int(m[3]) if m else 0


def _ccmixter(query, n, min_s=MIN_SECONDS, max_s=MAX_SECONDS):
    """ccMixter query API: text search over names/tags, licence filtered here (by, by-sa, cc0 only)."""
    # ccMixter repeats the whole JSON body in an "X-JSON" response header (40+ kB for two tracks), longer
    # than http.client's 64 kB header-line limit
    http.client._MAXLINE = max(http.client._MAXLINE, 4 * 1024 * 1024)
    d = []
    for how in ("all", "any"):  # every word first, any word as a fallback
        params = {"f": "json", "search": query, "search_type": how, "sort": "rank", "limit": min(40, max(5, n * 2))}
        raw, _ = _get(CCMIXTER + "?" + urllib.parse.urlencode(params), timeout=25)
        d = json.loads(raw.decode("utf-8", errors="replace"))  # some uploads carry cp1252 bytes
        if isinstance(d, list) and len(d) >= 3 or len(query.split()) < 2:
            break
    out = []
    for it in d if isinstance(d, list) else []:
        lic_url = (it.get("license_url") or "").replace("http://", "https://")
        m = re.search(r"/licenses/(by|by-sa)/([\d.]+)|/publicdomain/zero/([\d.]+)", lic_url)
        if not m:
            continue  # NC, ND, sampling+ ...
        lic = f"CC {m[1].upper()} {m[2]}" if m[1] else f"CC0 {m[3]}"
        f = next((x for x in it.get("files") or [] if (x.get("file_format_info") or {}).get("media-type") == "audio"
                  and str(x.get("download_url", "")).lower().endswith((".mp3", ".ogg", ".flac", ".wav"))), None)
        if not f:
            continue
        dur = _parse_mmss((f.get("file_format_info") or {}).get("ps"))
        if not min_s <= dur <= max_s:
            continue
        tags = [t for t in (it.get("upload_tags") or "").split(",") if t and t not in
                ("media", "audio", "mp3", "44k", "48k", "stereo", "mono", "CBR", "VBR", "attribution", "trackback")]
        extra = it.get("upload_extra") or {}
        try:
            bpm = float(extra.get("bpm")) if extra.get("bpm") else None
        except (TypeError, ValueError):
            bpm = None
        title, artist = it.get("upload_name") or "", it.get("user_real_name") or it.get("user_name") or ""
        out.append(_result(provider="ccmixter", id=str(it.get("upload_id")), title=title, artist=artist, duration=dur,
                           tags=tags, license=lic, license_url=lic_url, page_url=it.get("file_page_url"),
                           audio_url=f["download_url"], instrumental=False if VOCAL_TAGS & {t.lower() for t in tags}
                           else True if "instrumental" in tags else None,
                           attribution=f"\"{title}\" by {artist}, {lic}, via ccMixter", bpm_hint=bpm))
    return out


def _wikimedia(query, n, min_s=MIN_SECONDS, max_s=MAX_SECONDS):
    """Commons audio files; videoinfo gives the duration and an mp3/ogg derivative (smaller than wav/flac originals)."""
    params = {"action": "query", "format": "json", "formatversion": "2", "generator": "search",
              "gsrsearch": f"{query} music filetype:audio", "gsrnamespace": "6", "gsrlimit": min(50, max(1, n)),
              "prop": "videoinfo", "viprop": "url|size|mime|extmetadata|derivatives",
              "viextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|AttributionRequired|ImageDescription"}
    d = _get_json(COMMONS + "?" + urllib.parse.urlencode(params))
    pages = sorted(d.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        vi = (p.get("videoinfo") or [{}])[0]
        dur = float(vi.get("duration") or 0)
        if not min_s <= dur <= max_s or not str(vi.get("mime", "")).startswith(("audio/", "application/ogg")):
            continue
        md = {k: (v or {}).get("value", "") for k, v in (vi.get("extmetadata") or {}).items()}
        lic = _strip_html(md.get("LicenseShortName"))
        title = re.sub(r"^File:|\.\w+$", "", p.get("title", ""))
        if SPOKEN.search(title) or "Speaker:" in _strip_html(md.get("Artist")):
            continue  # pronunciation recordings and spoken Wikipedia articles
        title = re.sub(r"\s*\(ISRC [^)]*\)", "", title)
        artist = _strip_html(md.get("Artist")) or _strip_html(md.get("Credit"))
        url = vi.get("url") or ""
        if (vi.get("size") or 0) > 15 * 1024 * 1024 or not url.lower().endswith((".mp3", ".ogg", ".oga", ".opus")):
            url = next((x["src"] for x in vi.get("derivatives") or [] if "mpeg" in x.get("type", "") or "vorbis" in x.get("type", "")), url)
        out.append(_result(provider="wikimedia", id=str(p.get("pageid")), title=title, artist=artist, duration=round(dur, 1),
                           tags=[], license=lic, license_url=md.get("LicenseUrl") or None, page_url=vi.get("descriptionurl"),
                           audio_url=url, attribution=f"\"{title}\" by {artist or 'unknown author'}, {lic or 'see source'}, via Wikimedia Commons"))
    return out


VOCAL_TAGS = {"acappella", "acapella", "vocals", "female_vocals", "male_vocals", "singing", "spoken_word", "rap", "lyrics"}
SPOKEN = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z]{2,4})?-|spoken|-article$|pronunciation", re.I)


PROVIDERS = {"openverse": _openverse, "ccmixter": _ccmixter, "wikimedia": _wikimedia}


def _rank(r):
    """Instrumentals first (a bed under captions), then licence-clear, then a usable 60-240 s length."""
    return (r["instrumental"] is False, not r["license_clear"], not 60 <= (r["duration"] or 0) <= 240)


def search_music(query, n=10, providers=DEFAULT_PROVIDERS, min_seconds=MIN_SECONDS, max_seconds=MAX_SECONDS,
                 on_error=None, clear_only=True):
    """Searches the providers; returns up to n normalised results interleaved provider by provider:
    {provider, id, title, artist, duration (s), tags, license, license_url, page_url, audio_url, attribution,
     instrumental (True/False/None), bpm_hint (ccMixter), license_clear}. Vocal tracks sink to the end.
    A multi-word query with no hits is retried shorter (first two words, or the longest word)."""
    per = {}
    for name in providers:
        try:
            res = PROVIDERS[name](query, max(n * 2, 10), min_seconds, max_seconds)
            words = query.split()
            if not res and len(words) > 1:  # Openverse ANDs the words: retry with fewer
                shorter = " ".join(words[:2]) if len(words) > 2 else max(words, key=len)
                res = PROVIDERS[name](shorter, max(n * 2, 10), min_seconds, max_seconds)
            per[name] = sorted((r for r in res if r["license_clear"] or not clear_only), key=_rank)
        except Exception as e:
            per[name] = []
            on_error and on_error(name, str(e))
    out, seen = [], set()
    queues = [list(v) for v in per.values()]
    while len(out) < n and any(queues):
        for q in queues:
            while q:
                r = q.pop(0)
                key = (r["audio_url"] or "").split("&format=")[0]
                if key and key not in seen:
                    seen.add(key)
                    out.append(r)
                    break
            if len(out) >= n:
                break
    return sorted(out, key=_rank)


# ---------------------------------------------------------------- download + convert

def _ffmpeg(*args, timeout=180):
    p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *args], capture_output=True, timeout=timeout)
    if p.returncode:
        raise FetchError("ffmpeg: " + p.stderr.decode(errors="replace").strip()[-300:])
    return p


def to_wav(src, out, keep_seconds=KEEP_SECONDS):
    """Any audio -> 48 kHz stereo 16-bit wav, loudness-normalised like the built-in beds (I=-16, TP=-1.5)."""
    _ffmpeg("-i", str(src), "-map", "0:a:0", "-t", str(keep_seconds), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out), timeout=300)
    return out


def _key(r):
    return f"{r['provider']}:{r['id']}"


def download_music(results, dest_dir, max_tracks=6, on_event=None, timeout=60):
    """Downloads results (sequentially: the hosts throttle bursts) into <dest>/music/<slug>.wav, 40 MB cap,
    converted with to_wav. Each kept track gets a credits.json entry keyed "music/<slug>" with kind "music".
    Tracks already in credits (same provider id) are returned as they are. Returns the credit entries."""
    dest = Path(dest_dir)
    (dest / "music").mkdir(parents=True, exist_ok=True)
    credits = load_credits(dest)
    have = {c.get("source_key"): c for c in credits.values() if c.get("kind") == "music"}
    emit = on_event or (lambda *a: None)
    written = []
    for r in results:
        if len(written) >= max_tracks:
            break
        if _key(r) in have and Path(have[_key(r)]["path"]).exists():
            if have[_key(r)] not in written:
                written.append(have[_key(r)])
            continue
        cid, t0 = uuid.uuid4().hex[:8], time.time()
        emit("tool_call", {"id": cid, "name": "download_music", "args": {"url": r["audio_url"], "title": r["title"][:80]}})
        tmpdir = Path(tempfile.mkdtemp(prefix=".dl-", dir=dest / "music"))
        try:
            if "wikimedia.org/" in r["audio_url"]:
                with _wikimedia_lock:
                    # Commons throttles clients whose User-Agent has no contact address (robot policy,
                    # HTTP 429 + Retry-After: 10 after a couple of files); we send none on purpose, so wait it out
                    data, hdr = _get(r["audio_url"], timeout=timeout, retries=3, max_bytes=MAX_BYTES, accept="audio/*")
                    time.sleep(3.0)
            else:
                # ccMixter hotlink protection answers 403 without a Referer from its own site
                ref = {"Referer": r["page_url"]} if r["provider"] == "ccmixter" and r.get("page_url") else None
                data, hdr = _get(r["audio_url"], timeout=timeout, retries=2, max_bytes=MAX_BYTES, accept="audio/*", headers=ref)
            ctype = (hdr.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype.startswith(("text/", "image/")) or ctype == "application/json":
                raise FetchError(f"not audio: {ctype}")
            raw = tmpdir / "source"
            raw.write_bytes(data)
            artist = r.get("artist") or ""
            base = slugify(r["title"] if not artist or slugify(r["title"]).startswith(slugify(artist)) else f"{artist} {r['title']}", 48)
            slug, k = base, 2
            while f"music/{slug}" in credits or (dest / "music" / f"{slug}.wav").exists():
                slug, k = f"{base}-{k}", k + 1
            path = dest / "music" / f"{slug}.wav"
            to_wav(raw, path)
            entry = dict(r)
            entry.update(kind="music", asset_id=f"music/{slug}", group="music", path=str(path), file=f"music/{slug}.wav",
                         source_key=_key(r), source_bytes=len(data), saved_seconds=round(min(r["duration"] or KEEP_SECONDS, KEEP_SECONDS), 1),
                         downloaded_at=round(time.time()))
            credits[entry["asset_id"]] = entry
            _save_json(dest / "credits.json", credits)
            written.append(entry)
            have[entry["source_key"]] = entry
            emit("tool_result", {"id": cid, "name": "download_music", "ok": True, "seconds": round(time.time() - t0, 2),
                                 "result": {"asset_id": entry["asset_id"], "license": r["license"], "mb": round(len(data) / 1e6, 1)}})
        except Exception as e:
            emit("tool_result", {"id": cid, "name": "download_music", "ok": False, "seconds": round(time.time() - t0, 2),
                                 "result": {"error": str(e)[:200], "url": r["audio_url"]}})
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return written


# ---------------------------------------------------------------- analysis

BANDS = ("lowpass=f=150", "bandpass=f=800:width_type=o:w=2", "highpass=f=3000")


def envelopes(path, rate=FRAME_RATE, seconds=None):
    """Mean power of 3 bands (low/mid/high) at `rate` frames per second, computed by ffmpeg
    (band filter -> square -> resample, the resampler's anti-alias filter does the averaging).
    Returns three lists of floats of equal length."""
    chains = ";".join(f"[s{i}]{f},aeval='val(0)*val(0)',aresample={rate},aformat=sample_fmts=flt:channel_layouts=mono[b{i}]" for i, f in enumerate(BANDS))
    graph = (f"[0:a]aformat=channel_layouts=mono,aresample=22050,asplit={len(BANDS)}" + "".join(f"[s{i}]" for i in range(len(BANDS)))
             + ";" + chains + ";" + "".join(f"[b{i}]" for i in range(len(BANDS))) + f"amerge=inputs={len(BANDS)}[out]")
    args = ["-i", str(path)] + (["-t", str(seconds)] if seconds else []) + ["-filter_complex", graph, "-map", "[out]", "-f", "f32le", "-"]
    data = _ffmpeg(*args, timeout=300).stdout
    a = array("f")
    a.frombytes(data[: len(data) // 4 * 4])
    k = len(BANDS)
    return [[max(0.0, x) for x in a[i::k]] for i in range(k)]


def onset_strength(bands, rate=FRAME_RATE, weights=(2.0, 1.0, 1.0), compress=10.0):
    """Log-compressed band flux, summed over bands, minus a 0.5 s moving average, half-wave rectified.
    The low band counts double and the compression is mild, so kicks decide the beat phase when hats and
    arpeggios are as dense as the beat itself (the synthesized chiptune is otherwise half a beat off)."""
    n = min(len(b) for b in bands)
    flux = [0.0] * n
    for b, wt in zip(bands, weights):
        peak = max(b[:n]) or 1.0
        prev = 0.0
        for i in range(n):
            v = math.log1p(compress * b[i] / peak)
            d = v - prev
            if d > 0:
                flux[i] += wt * d
            prev = v
    w = rate // 2
    out, acc = [0.0] * n, 0.0
    for i in range(n):
        acc += flux[i] - (flux[i - w] if i >= w else 0.0)
        out[i] = max(0.0, flux[i] - acc / min(i + 1, w))
    return out


def _autocorr(x, lo, hi):
    n = len(x)
    m = sum(x) / n
    y = [v - m for v in x]
    return {lag: sum(y[i] * y[i + lag] for i in range(n - lag)) / (n - lag) for lag in range(lo, hi + 1)}


def estimate_tempo(onset, rate=FRAME_RATE, lo_bpm=60, hi_bpm=200, prior_bpm=120, window=90.0):
    """Tempo from the onset autocorrelation of the busiest `window` seconds. Each lag scores its own
    autocorrelation plus half of the double lag's (a comb, so the true period beats its harmonics), times a
    log-Gaussian prior around 120 bpm (resolves octave errors the way a listener would). Parabolic
    interpolation gives sub-frame precision. Returns (bpm, confidence 0..1)."""
    span = int(window * rate)
    if len(onset) > span:  # pick the window with the most onset energy
        best, acc, start = -1, sum(onset[:span]), 0
        for i in range(span, len(onset), rate):
            acc = sum(onset[i - span + rate:i + rate]) if i + rate <= len(onset) else acc
            if acc > best:
                best, start = acc, i - span + rate
        onset = onset[start:start + span]
    lo, hi = int(rate * 60 / hi_bpm), int(math.ceil(rate * 60 / lo_bpm))
    ac = _autocorr(onset, 1, 2 * hi + 2)
    zero = sum((v - sum(onset) / len(onset)) ** 2 for v in onset) / len(onset) or 1.0
    score = {}
    for lag in range(lo, hi + 1):
        bpm = 60 * rate / lag
        prior = math.exp(-0.5 * (math.log2(bpm / prior_bpm) / 1.0) ** 2)
        score[lag] = (ac[lag] + 0.5 * ac.get(2 * lag, 0.0)) * prior
    lag = max(score, key=score.get)
    a, b, c = score.get(lag - 1, score[lag]), score[lag], score.get(lag + 1, score[lag])
    shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) < 0 else 0.0
    period = lag + max(-0.5, min(0.5, shift))
    return round(60 * rate / period, 1), round(max(0.0, min(1.0, ac[lag] / zero)), 3)


def track_beats(onset, bpm, rate=FRAME_RATE, tightness=100.0):
    """Dynamic-programming beat tracker (Ellis 2007): beats sit on strong onsets while their spacing stays
    close to the tempo period. Returns beat times in seconds."""
    n = len(onset)
    if not n or not bpm:
        return []
    period = 60 * rate / bpm
    sd = (sum(v * v for v in onset) / n) ** 0.5 or 1.0
    loc = [v / sd for v in onset]
    score, back = loc[:], [-1] * n
    lo, hi = int(round(period / 2)), int(round(period * 2))
    for i in range(lo, n):
        best, arg = -1e30, -1
        for j in range(max(0, i - hi), i - lo + 1):
            s = score[j] - tightness * math.log((i - j) / period) ** 2
            if s > best:
                best, arg = s, j
        if arg >= 0:
            score[i] = loc[i] + best
            back[i] = arg
    # end on the best-scoring frame within the last period
    tail = range(max(0, n - int(period) - 1), n)
    i = max(tail, key=lambda k: score[k])
    beats = []
    while i >= 0:
        beats.append(i)
        i = back[i]
    beats.reverse()
    # the DP may start late; extend backwards by the period on onset peaks
    while beats and beats[0] - period > 0:
        g = int(round(beats[0] - period))
        w = max(1, int(period / 10))
        cand = max(range(max(0, g - w), min(n, g + w + 1)), key=lambda k: loc[k])
        beats.insert(0, cand)
    return [round(b / rate, 3) for b in beats]


def energy_curve(bands, rate=FRAME_RATE, step=0.5):
    """Loudness in dB (relative, full band ~ sum of the bands) every `step` seconds."""
    n, hop = min(len(b) for b in bands), int(rate * step)
    out = []
    for i in range(0, n - hop + 1, hop):
        p = sum(sum(b[i:i + hop]) for b in bands) / hop
        out.append(round(10 * math.log10(p + 1e-12), 2))
    return out


def find_drop(energy, step=0.5, window=DROP_WINDOW, beats=None):
    """Start of the loudest `window`-second stretch (the chorus / drop), moved to the nearest beat at or
    before it. Returns (seconds, mean dB of the window)."""
    k = max(1, int(window / step))
    if len(energy) <= k:
        return 0.0, (sum(energy) / len(energy) if energy else -120.0)
    lin = [10 ** (e / 10) for e in energy]
    acc = sum(lin[:k])
    best, at = acc, 0
    for i in range(k, len(lin)):
        acc += lin[i] - lin[i - k]
        if acc > best:
            best, at = acc, i - k + 1
    t = at * step
    if beats:
        before = [b for b in beats if b <= t + 0.25]
        t = before[-1] if before else beats[0]
    return round(t, 3), round(10 * math.log10(best / k + 1e-12), 2)


def analyse(path, max_seconds=KEEP_SECONDS):
    """bpm, beats (s), energy curve (dB per 0.5 s), first_sound (end of a silent intro) and best_start (drop)."""
    t0 = time.time()
    bands = envelopes(path, seconds=max_seconds)
    onset = onset_strength(bands)
    bpm, conf = estimate_tempo(onset)
    beats = track_beats(onset, bpm)
    energy = energy_curve(bands)
    top = max(energy) if energy else 0
    first = next((i * 0.5 for i, e in enumerate(energy) if e > top - 30), 0.0)
    best, best_db = find_drop(energy, beats=beats)
    # mean inter-beat interval of the tracked beats is a more precise tempo than the lag peak
    if len(beats) > 8:
        ibi = sorted(b - a for a, b in zip(beats, beats[1:]))
        med = ibi[len(ibi) // 2]
        good = [x for x in ibi if abs(x - med) < 0.1 * med]
        if good:
            bpm = round(60 / (sum(good) / len(good)), 1)
    return {"duration": round(len(energy) * 0.5, 1), "bpm": bpm, "tempo_confidence": conf, "beats": beats,
            "energy": energy, "first_sound": first, "best_start": best, "best_db": best_db,
            "seconds": round(time.time() - t0, 2)}


def _analysis_cached(path, cache):
    p = Path(path)
    key, mtime = str(p), p.stat().st_mtime
    hit = cache.get(key)
    if hit and hit.get("mtime") == mtime:
        return hit["analysis"]
    a = analyse(p)
    cache[key] = {"mtime": mtime, "analysis": a}
    return a


# ---------------------------------------------------------------- gather (model-driven)

QUERY_SCHEMA = {
    "type": "object",
    "properties": {"moods": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
        "type": "object",
        "properties": {"mood": {"type": "string"},
                       "queries": {"type": "array", "minItems": 3, "maxItems": 6, "items": {"type": "string"}}},
        "required": ["mood", "queries"]}}},
    "required": ["moods"]}

QUERY_PROMPT = """Ты подбираешь фоновую музыку (без слов) для вертикального видеоролика. Задача пользователя:
«{task}»

Нужные настроения музыки (mood) и что под ними подразумевается:
{moods}

Для КАЖДОГО настроения дай 3-6 поисковых запросов НА АНГЛИЙСКОМ для каталога свободной музыки (Jamendo, ccMixter):
1-3 простых слова — жанр, инструмент, настроение, например "acoustic guitar warm", "dark synthwave", "piano emotional",
"chiptune", "horror ambient", "cinematic epic". Без кавычек, названий песен и имён исполнителей."""

# used when there is no model (or it fails): a few generic queries per word of the mood name
FALLBACK_QUERIES = {
    "warm": ["acoustic warm", "piano emotional", "happy ukulele"], "family": ["acoustic family", "warm piano"],
    "dark": ["dark ambient", "dark synth"], "horror": ["horror ambient", "creepy"], "retro": ["synthwave", "retro 80s"],
    "epic": ["cinematic epic", "epic orchestral", "trailer"], "chiptune": ["chiptune", "8bit"],
    "happy": ["happy upbeat", "ukulele"], "sad": ["sad piano", "melancholic"], "calm": ["calm ambient", "lofi chill"],
    "energetic": ["energetic rock", "upbeat electronic"], "drone": ["dark drone", "ambient drone"], "pad": ["ambient pad"],
}


def plan_music_queries(task_text, llm, moods):
    """moods: {name: description} -> {name: [queries]} (model with a JSON schema; keyword fallback)."""
    out = {}
    if llm is not None:
        schema = json.loads(json.dumps(QUERY_SCHEMA))
        schema["properties"]["moods"]["items"]["properties"]["mood"]["enum"] = list(moods)
        text = "\n".join(f"- {k}: {v or k.replace('_', ' ')}" for k, v in moods.items())
        res, _ = llm.json([{"role": "user", "content": QUERY_PROMPT.format(task=task_text, moods=text)}], schema,
                          max_tokens=700, temperature=0.2)
        for m in res.get("moods", []):
            qs = out.setdefault(m.get("mood"), [])
            for q in m.get("queries", []):
                q = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 '\-]", " ", q)).strip()
                if q and len(qs) < 6 and q.lower() not in {x.lower() for x in qs}:
                    qs.append(q)
    for name in moods:
        if not out.get(name):
            words = re.findall(r"[a-z0-9]+", name.lower())
            qs = [q for w in words for q in FALLBACK_QUERIES.get(w, [])] or [" ".join(words)]
            out[name] = list(dict.fromkeys(qs))[:6]
    return {k: v for k, v in out.items() if k in moods}


def gather_music(task_text, llm, dest_dir, moods, per_mood=2, per_query=6, providers=DEFAULT_PROVIDERS,
                 queries=None, on_event=None):
    """Task text + mood names -> a library of downloaded, analysed, licence-tracked tracks:
    [{id, path, title, artist, mood, mood_tags, bpm, beats, duration, best_start, first_sound, license,
      license_url, page_url, attribution, provider}], also saved to <dest>/music/library.json.
    moods: ["warm", ...] or {"warm": "семейные воспоминания", ...}. queries: {mood: [...]} skips the model.
    llm may be None (keyword fallback queries)."""
    dest = Path(dest_dir).expanduser()
    (dest / "music").mkdir(parents=True, exist_ok=True)
    moods = dict(moods) if isinstance(moods, dict) else {m: "" for m in moods}
    emit = on_event or (lambda *a: None)

    def step(name, args, fn):
        cid, t0 = uuid.uuid4().hex[:8], time.time()
        emit("tool_call", {"id": cid, "name": name, "args": args})
        try:
            res = fn()
        except Exception as e:
            emit("tool_result", {"id": cid, "name": name, "ok": False, "seconds": round(time.time() - t0, 2), "result": {"error": str(e)[:300]}})
            raise
        return res, (lambda summary: emit("tool_result", {"id": cid, "name": name, "ok": True, "seconds": round(time.time() - t0, 2), "result": summary}))

    if queries is None:
        try:
            queries, done = step("plan_music_queries", {"task": task_text, "moods": list(moods)}, lambda: plan_music_queries(task_text, llm, moods))
        except Exception as e:  # the model is optional here
            emit("warning", {"message": f"music queries: {str(e)[:200]}, using keyword queries"})
            queries, done = step("plan_music_queries", {"moods": list(moods), "fallback": True}, lambda: plan_music_queries(task_text, None, moods))
        done({"queries": queries})
    lib_path = dest / "music" / "library.json"
    saved = json.loads(lib_path.read_text()) if lib_path.exists() else {}
    cache = saved.pop("_analysis", {})
    library, used = [], set()
    for mood, qs in queries.items():
        cands, seen = [], set()
        for rank, q in enumerate(qs):
            res, done = step("search_music", {"query": q, "mood": mood, "providers": list(providers)},
                             lambda: search_music(q, per_query, providers, on_error=lambda p, e: emit("warning", {"message": f"{p}: {e}"})))
            done({"count": len(res), "by_provider": {p: sum(r["provider"] == p for r in res) for p in providers}})
            for pos, r in enumerate(res):
                if _key(r) not in seen and _key(r) not in used:
                    seen.add(_key(r))
                    cands.append((_rank(r), pos, rank, r))
        cands.sort(key=lambda c: c[:3])  # instrumental + clear licence first, then each query's best hits
        got, done = step("download_music", {"mood": mood, "candidates": len(cands), "max": per_mood},
                         lambda: download_music([c[3] for c in cands[: per_mood * 4]], dest, per_mood, on_event=on_event))
        done({"downloaded": len(got)})
        for e in got:
            used.add(e["source_key"])
            res, done = step("analyse_music", {"track": e["asset_id"]}, lambda: _analysis_cached(e["path"], cache))
            done({k: res[k] for k in ("bpm", "tempo_confidence", "best_start", "duration")})
            entry = {"id": e["asset_id"], "path": e["path"], "title": e["title"], "artist": e["artist"], "mood": mood,
                     "mood_tags": [mood] + [t for t in e.get("tags") or [] if t][:6], "bpm": res["bpm"],
                     "tempo_confidence": res["tempo_confidence"], "beats": res["beats"], "duration": res["duration"],
                     "best_start": res["best_start"], "first_sound": res["first_sound"], "license": e["license"],
                     "license_url": e["license_url"], "page_url": e["page_url"], "attribution": e["attribution"],
                     "provider": e["provider"], "instrumental": e.get("instrumental"), "bpm_hint": e.get("bpm_hint")}
            library.append(entry)
            saved[entry["id"]] = entry
    saved["_analysis"] = cache
    _save_json(lib_path, saved)
    emit("tool_result", {"id": "gather_music", "name": "gather_music", "ok": True, "seconds": 0,
                         "result": {"tracks": len(library), "licenses": sorted({t["license"] for t in library})}})
    return library


def load_library(dest_dir):
    """Previously gathered tracks of a folder: {id: entry} (feed it to EDL.music_library)."""
    p = Path(dest_dir).expanduser() / "music" / "library.json"
    d = json.loads(p.read_text()) if p.exists() else {}
    return {k: v for k, v in d.items() if not k.startswith("_") and Path(v["path"]).exists()}


def library_for_prompt(library):
    """Compact view for a model prompt (no beat lists)."""
    items = library.values() if isinstance(library, dict) else library
    return [{"id": t["id"], "mood": t["mood"], "title": t["title"][:50], "bpm": t["bpm"], "seconds": t["duration"],
             "drop_at": t["best_start"], "tags": t["mood_tags"][1:5]} for t in items]


# ---------------------------------------------------------------- beat snapping

def beat_snap(durations, beats, offset=0.0, min_seconds=0.6, max_seconds=8.0, tolerance=0.05, every=1, snap_end=True):
    """Nudges shot durations so the cuts land on beats. Pure function.
    durations: shot lengths of one section (s); beats: beat times of the track (s); offset: track time at the
    section's first cut (EDL.section_track_time); min/max_seconds: a number or one per shot; every: snap to
    every n-th beat (2 = half time, 4 = bars if the first beat is a downbeat); snap_end: also snap the cut
    after the last shot. Each cut moves to the nearest grid beat within half a grid step and within
    ±tolerance of the section total, keeping every shot inside its limits. Cuts are snapped independently
    of each other, so the error never accumulates: the total changes by at most half a grid step.
    Returns (new_durations, {"moved", "on_beat", "max_shift", "total_before", "total_after"})."""
    n = len(durations)
    lo = [min_seconds] * n if isinstance(min_seconds, (int, float)) else list(min_seconds)
    hi = [max_seconds] * n if isinstance(max_seconds, (int, float)) else list(max_seconds)
    total = sum(durations)
    grid = [b - offset for b in beats[::max(1, int(every))] if b - offset > 0]
    if not grid or not n:
        return list(durations), {"moved": 0, "on_beat": 0, "max_shift": 0.0, "total_before": round(total, 3), "total_after": round(total, 3)}
    step = (grid[-1] - grid[0]) / (len(grid) - 1) if len(grid) > 1 else 0.5
    slack = tolerance * total
    cuts, prev, orig, on, shifts = [], 0.0, 0.0, 0, []
    for k, d in enumerate(durations):
        orig += d
        last = k == n - 1
        target = None
        if not last or snap_end:
            i = bisect.bisect_left(grid, orig)
            for g in sorted(grid[max(0, i - 2):i + 2], key=lambda g: abs(g - orig)):
                if abs(g - orig) > min(step / 2 + 1e-6, slack):
                    continue
                if not lo[k] - 1e-6 <= g - prev <= hi[k] + 1e-6:
                    continue
                if not last and (orig + durations[k + 1]) - g < lo[k + 1] - 1e-6:  # leave room for the next shot
                    continue
                target = g
                on += 1
                break
        if target is None:  # unsnapped cut: keep its original place, inside the limits
            target = min(max(orig, prev + lo[k]), prev + hi[k])
        shifts.append(abs(target - orig))
        cuts.append(target)
        prev = target
    out = [round(b - a, 3) for a, b in zip([0.0] + cuts[:-1], cuts)]
    return out, {"moved": sum(s > 0.005 for s in shifts), "on_beat": on, "max_shift": round(max(shifts), 3),
                 "total_before": round(total, 3), "total_after": round(sum(out), 3)}


def snap_edl(edl, sections=None, every=1, tolerance=0.05):
    """Applies beat_snap to every section (or the named ones) whose music is a library track with beats,
    in timeline order (each snap shifts the following sections, and section_track_time follows). Returns
    {section: report}. Shot limits are the EDL's (LIMITS picture/card seconds)."""
    from .edl import LIMITS
    reports = {}
    for sec in edl.sections:
        if sections and sec.name not in sections:
            continue
        track = edl.music_library.get(sec.music)
        if not track or not track.get("beats"):
            continue
        bed, offset = edl.section_track_time(sec.name)
        idx = edl.section_shots(sec.name)
        if bed is None or not idx:
            continue
        shots = [edl.shots[i] for i in idx]
        from .tools import shot_limits  # same limits as polish edits, incl. the 0.8 s floor for shots with text
        lim = [shot_limits(s) for s in shots]
        new, rep = beat_snap([s.seconds for s in shots], track["beats"], offset, [x[0] for x in lim], [x[1] for x in lim],
                             tolerance, every)
        for s, d in zip(shots, new):
            s.seconds = d
            if s.kind == "picture" and s.speed != 100:
                s.speed = edl.fit_speed(s.speed, d, [])
        reports[sec.name] = rep
    return reports
