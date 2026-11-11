"""Instagram access (steps 1-3). Only ever opens the saved-collection pages and
the media-info API for reels found on them (hard rule 1).

  python ig.py login                 # opens a window; you log in yourself (never automated)
  python ig.py collections           # prints name -> URL for each saved collection (for config.yaml)
  python ig.py sync  "cool cs"       # list + fetch via the collection feed (~20 reels per request)
  python ig.py sync  "all saved"     # no collections? every saved post (needs ingest_all_saved: true)
  python ig.py list  "cool cs"       # fallback: scroll the grid -> data/queue_<collection>.json
  python ig.py fetch "cool cs"       # fallback: one media/info call per queued reel

Per reel it saves meta.json (with the stream URLs), audio.m4a, or img_N.jpg for photos.
Video is never downloaded; process.py pulls only the frames it needs from the URL.

Exit codes: 0 ok, 3 login/challenge needed, 4 rate-limited, 5 feed unavailable (use list + fetch).
On 3 or 4, stop and ask the user.
"""
import json, re, sys, time
from playwright.sync_api import sync_playwright
from media import streams, safe_cdn
from config import (COLLECTIONS, PROFILE, DATA, SYNC, IG_APP_ID, REQUEST_GAP_S, MAX_NEW_PER_RUN,
                    INSTAGRAM_USER, ALL_SAVED, allowed, code_dir)

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
CODE_RE = re.compile(r"/(?:reel|p)/([A-Za-z0-9_-]+)")


def media_id(shortcode: str) -> str:
    n = 0
    for ch in shortcode[:11]:          # longer codes carry a private suffix
        n = n * 64 + ALPHABET.index(ch)
    return str(n)


def synced_codes() -> set:
    if not SYNC.exists():
        return set()
    s = json.loads(SYNC.read_text())
    return {c for v in s.get("synced", {}).values() for c in v.get("codes", [])}


def open_ctx(p, headless=False):
    # Always a visible window: headless Chromium sends "HeadlessChrome" in its user agent,
    # and Instagram responds by dropping the saved session (sessionid cookie).
    return p.chromium.launch_persistent_context(str(PROFILE), headless=headless,
                                                viewport={"width": 1200, "height": 900})


def blocked(page) -> bool:
    u = page.url
    return "accounts/login" in u or "challenge" in u or "two_factor" in u


def cmd_login():
    with sync_playwright() as p:
        ctx = open_ctx(p, headless=False)
        page = ctx.new_page()
        page.goto("https://www.instagram.com/accounts/login/")
        print("Log in in the browser window (including 2FA). Waiting up to 10 min…", flush=True)
        for _ in range(300):
            if any(c["name"] == "sessionid" for c in ctx.cookies()):
                print("Logged in; profile saved.")
                ctx.close()
                return
            time.sleep(2)
        ctx.close()
        sys.exit(3)


def cmd_collections():
    """Open only <user>/saved/ and print every collection link on it."""
    if not INSTAGRAM_USER:
        raise SystemExit("Set instagram_user in config.yaml first.")
    base = f"https://www.instagram.com/{INSTAGRAM_USER}/saved/"
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        time.sleep(3)
        if blocked(page):
            print("Instagram wants a login/challenge. Run: python ig.py login"); sys.exit(3)
        links = page.eval_on_selector_all(
            f'main a[href*="/{INSTAGRAM_USER}/saved/"]',
            "els => els.map(e => [e.getAttribute('href'), (e.innerText || '').trim()])")
        ctx.close()
    seen = {}
    for href, text in links:
        m = re.search(rf"/{re.escape(INSTAGRAM_USER)}/saved/([^/]+)/(\d+)/?", href or "")
        if m:
            name = (text.splitlines()[0] if text else m.group(1).replace("-", " ")).strip()
            seen[name] = "https://www.instagram.com" + m.group(0).rstrip("/") + "/"
    print("collections:")
    for name, url in seen.items():
        print(f"  {name}: {url}")


def cmd_list(collection: str):
    allowed(collection)
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.new_page()
        page.goto(COLLECTIONS[collection], wait_until="domcontentloaded")
        time.sleep(3)
        if blocked(page):
            print("Instagram wants a login/challenge. Run: python ig.py login"); sys.exit(3)
        seen, still = [], 0
        while still < 4:
            hrefs = page.eval_on_selector_all(
                'main a[href*="/reel/"], main a[href*="/p/"]', "els => els.map(e => e.getAttribute('href'))")
            new = [m.group(1) for h in hrefs if (m := CODE_RE.search(h or "")) and m.group(1) not in seen]
            seen += new
            still = 0 if new else still + 1
            page.mouse.wheel(0, 4000)
            time.sleep(1.5)
        ctx.close()
    done = synced_codes()
    queue = [c for c in seen if c not in done]
    out = DATA / f"queue_{collection.replace(' ', '_')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"collection": collection, "codes": queue}, indent=1))
    print(f"{collection}: {len(seen)} on page, {len(queue)} new -> {out}")
    if len(queue) > MAX_NEW_PER_RUN:
        print(f"MORE THAN {MAX_NEW_PER_RUN} NEW REELS: confirm with the user before fetching.")


def api_get(page, path):
    """GET an Instagram web-API path from inside the logged-in page (cookies apply)."""
    r = page.evaluate("""async ([path, app]) => {
        const r = await fetch(path, {headers: {'x-ig-app-id': app}, credentials: 'include'});
        return {status: r.status, text: await r.text()};
    }""", [path, IG_APP_ID])
    time.sleep(REQUEST_GAP_S)
    if r["status"] == 429:
        print(f"429 rate-limited on {path}; stopping."); sys.exit(4)
    try:
        return json.loads(r["text"])
    except Exception:
        return {"_status": r["status"]}


def get_bytes(ctx, url, tries=3):
    """CDN download with retries; returns None after `tries` failures instead of crashing."""
    for t in range(tries):
        try:
            resp = ctx.request.get(url, timeout=60_000)
            time.sleep(REQUEST_GAP_S)
            if resp.ok:
                return resp.body()
        except Exception as e:
            print(f"  download retry {t + 1}/{tries}: {type(e).__name__}", flush=True)
        time.sleep(2 ** (t + 1))
    return None


def save_media(ctx, d, item):
    """Audio (small) and photos only. Video is NOT downloaded: process.py reads just the frames
    it needs straight from the CDN URL stored in meta.json. Missing files are retried next run."""
    audio, video = streams(item)
    item["_audio_url"], item["_video_url"] = audio, video
    (d / "meta.json").write_text(json.dumps(item))
    failed = []
    if audio and not (d / "audio.m4a").exists():
        b = get_bytes(ctx, audio)
        (d / "audio.m4a").write_bytes(b) if b else failed.append("audio")
    if not audio and not video:   # photo or carousel
        for j, m in enumerate(item.get("carousel_media") or [item]):
            c = m.get("image_versions2", {}).get("candidates", [])
            url = safe_cdn(c[0]["url"]) if c else None
            if url and not (d / f"img_{j}.jpg").exists():
                b = get_bytes(ctx, url)
                (d / f"img_{j}.jpg").write_bytes(b) if b else failed.append(f"img_{j}")
    return failed


def cmd_sync(collection: str):
    """List + fetch in one pass via the collection's feed: ~20 reels with full metadata per
    request, instead of scrolling the grid and calling media/info once per reel."""
    allowed(collection)
    if collection == ALL_SAVED:      # no collections: page through every saved post instead
        feed = "/api/v1/feed/saved/posts/"
    else:
        feed = f"/api/v1/feed/collection/{COLLECTIONS[collection].rstrip('/').rsplit('/', 1)[-1]}/posts/"
    done = synced_codes()      # reels already ingested from any collection are skipped
    queue, failed, max_id, pages = [], {}, "", 0
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.new_page()
        page.goto(COLLECTIONS[collection], wait_until="domcontentloaded")   # cookies + origin
        time.sleep(2)
        if blocked(page):
            print("Instagram wants a login/challenge. Run: python ig.py login"); sys.exit(3)
        while True:
            data = api_get(page, feed + (f"?max_id={max_id}" if max_id else ""))
            pages += 1
            if "items" not in data:
                print(f"Collection feed unavailable (HTTP {data.get('_status')}). "
                      f"Fall back to: ig.py list + ig.py fetch"); sys.exit(5)
            fresh = 0
            for wrapper in data["items"]:
                item = wrapper.get("media", wrapper)
                code = item.get("code")
                if not code or code in done:
                    continue
                fresh += 1
                queue.append(code)
                item["_collection"] = collection
                bad = save_media(ctx, code_dir(code), item)
                if bad: failed[code] = bad
                print(f"[{len(queue)}] {code}" + (f"  missing: {bad}" if bad else ""), flush=True)
                if len(queue) > MAX_NEW_PER_RUN:
                    print(f"MORE THAN {MAX_NEW_PER_RUN} NEW REELS: stopping; confirm with the user."); break
            max_id = data.get("next_max_id")
            # Saved items come newest first, so a page with nothing new means the rest is synced.
            if not data.get("more_available") or not max_id or fresh == 0 or len(queue) > MAX_NEW_PER_RUN:
                break
        ctx.close()
    out = DATA / f"queue_{collection.replace(' ', '_')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"collection": collection, "codes": queue}, indent=1))
    print(f"{collection}: {len(queue)} new in {pages} feed request(s) -> {out}")
    if failed:
        print(f"{len(failed)} reel(s) with missing files (re-run sync to retry): {failed}")


def cmd_fetch(collection: str):
    """Fallback for when the collection feed fails: one media/info call per queued reel.
    Resumes per file, so a timed-out download is retried on the next run."""
    allowed(collection)
    q = DATA / f"queue_{collection.replace(' ', '_')}.json"
    codes = json.loads(q.read_text())["codes"]
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.new_page()
        page.goto(COLLECTIONS[collection], wait_until="domcontentloaded")   # cookies + origin
        time.sleep(2)
        if blocked(page):
            print("Login/challenge needed."); sys.exit(3)
        for i, code in enumerate(codes, 1):
            d = code_dir(code)
            if (d / "meta.json").exists():
                item = json.loads((d / "meta.json").read_text())
            else:
                data = api_get(page, f"/api/v1/media/{media_id(code)}/info/")
                if not data.get("items"):
                    print(f"Empty/odd response for {code} (HTTP {data.get('_status')}); stopping."); sys.exit(4)
                item = data["items"][0]
                item["_collection"] = collection
            bad = save_media(ctx, d, item)
            print(f"[{i}/{len(codes)}] {code}" + (f"  missing: {bad}" if bad else ""), flush=True)
        ctx.close()


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    {"login": cmd_login, "collections": cmd_collections, "sync": lambda: cmd_sync(args[0]), "list": lambda: cmd_list(args[0]), "fetch": lambda: cmd_fetch(args[0])}.get(
        cmd, lambda: print(__doc__))()
