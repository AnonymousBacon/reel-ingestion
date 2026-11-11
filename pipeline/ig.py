"""Instagram access (steps 1-3). Only ever opens the saved-collection pages and
the media-info API for reels found on them (hard rule 1).

  python ig.py login                 # opens a window; you log in yourself (never automated)
  python ig.py collections           # prints name -> URL for each saved collection (for config.yaml)
  python ig.py list  "cool cs"       # -> data/queue_<collection>.json (new codes only)
  python ig.py fetch "cool cs"       # meta.json, audio.m4a, video.mp4 / images per code

Exit codes: 0 ok, 3 login/challenge needed, 4 rate-limited. On 3 or 4, stop and ask the user.
"""
import json, re, sys, time
import xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright
from config import (COLLECTIONS, PROFILE, DATA, SYNC, IG_APP_ID, REQUEST_GAP_S, MAX_NEW_PER_RUN,
                    INSTAGRAM_USER, allowed, code_dir)

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


def open_ctx(p, headless=True):
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


def pick_streams(mpd: str):
    """Return (audio_url, video_url) from a DASH manifest."""
    root = ET.fromstring(mpd)
    audio, videos = None, []
    for aset in root.iter():
        if not aset.tag.endswith("AdaptationSet"):
            continue
        set_mime = aset.get("mimeType") or aset.get("contentType") or ""   # mime can live here
        for rep in aset:
            if not rep.tag.endswith("Representation"):
                continue
            mime = rep.get("mimeType") or set_mime
            base = next((e.text for e in rep.iter() if e.tag.endswith("BaseURL")), None)
            if not base:
                continue
            if mime.startswith("audio"):
                audio = audio or base
            elif int(rep.get("width") or 0) >= 480:
                videos.append((int(rep.get("bandwidth") or 0), base))
    return audio, (min(videos)[1] if videos else None)


def cmd_fetch(collection: str):
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
                continue
            r = page.evaluate("""async ([id, app]) => {
                const r = await fetch(`/api/v1/media/${id}/info/`,
                    {headers: {'x-ig-app-id': app}, credentials: 'include'});
                return {status: r.status, text: await r.text()};
            }""", [media_id(code), IG_APP_ID])
            time.sleep(REQUEST_GAP_S)
            if r["status"] == 429:
                print(f"429 rate-limited at {code}; stopping."); sys.exit(4)
            try:
                item = json.loads(r["text"])["items"][0]
            except Exception:
                print(f"Empty/odd response for {code} (HTTP {r['status']}); stopping."); sys.exit(4)
            item["_collection"] = collection
            (d / "meta.json").write_text(json.dumps(item))
            dl = lambda url, name: ((d / name).write_bytes(ctx.request.get(url).body()), time.sleep(REQUEST_GAP_S))
            if item.get("video_dash_manifest"):
                a, v = pick_streams(item["video_dash_manifest"])
                if a: dl(a, "audio.m4a")
                if v: dl(v, "video.mp4")
            elif item.get("video_versions"):
                dl(min(item["video_versions"], key=lambda x: x.get("width", 9999))["url"], "video.mp4")
            else:   # photo or carousel: images only
                media = item.get("carousel_media") or [item]
                for j, m in enumerate(media):
                    c = m.get("image_versions2", {}).get("candidates", [])
                    if c: dl(c[0]["url"], f"img_{j}.jpg")
            print(f"[{i}/{len(codes)}] {code}", flush=True)
        ctx.close()


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    {"login": cmd_login, "collections": cmd_collections, "list": lambda: cmd_list(args[0]), "fetch": lambda: cmd_fetch(args[0])}.get(
        cmd, lambda: print(__doc__))()
