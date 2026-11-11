"""Steps 4-5 plus pre-research, all local and free (no LLM tokens).

  python process.py "cool cs"

For each fetched reel: 16 kHz WAV -> Whisper -> transcript.txt; 3-8 frames -> OCR -> ocr.txt;
URL / owner/repo extraction; GitHub lookups via `gh api` -> repos.json; then one compact
brief.json that is the ONLY file the agents need to read.
"""
import json, re, subprocess, sys
from datetime import datetime, timezone
from config import DATA, WHISPER_MODEL, allowed
from media import streams

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
GH_RE = re.compile(r"github\.com/([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)")
SLUG_RE = re.compile(r"\b([A-Za-z0-9-]{2,39}/[A-Za-z0-9_.-]{2,100})\b")
RESOURCE_WORDS = re.compile(r"github|repo|open[- ]source|\.com|\.dev|\.ai|\.io|course|extension|"
                            r"plugin|skill|library|framework|\bapp\b|tool|install|npm|pip", re.I)


def sh(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def video_src(d):
    """Local video.mp4 (older runs) or the CDN URL saved in meta.json. ffmpeg reads the URL
    with range requests, so frame grabs fetch only the bytes they need."""
    if (d / "video.mp4").exists():
        return str(d / "video.mp4")
    meta = json.loads((d / "meta.json").read_text())
    return meta.get("_video_url") or streams(meta)[1]


def transcribe(d):
    src = str(d / "audio.m4a") if (d / "audio.m4a").exists() else video_src(d)
    if not src:
        return "", []
    wav = d / "audio.wav"
    sh("ffmpeg", "-y", "-i", src, "-vn", "-ar", "16000", "-ac", "1", str(wav))
    import mlx_whisper
    r = mlx_whisper.transcribe(str(wav), path_or_hf_repo=WHISPER_MODEL, language="en")
    text = r["text"].strip()
    (d / "transcript.txt").write_text(text)
    segs = [{"t": round(s["start"], 1), "text": s["text"].strip(),
             "logprob": round(s["avg_logprob"], 2), "no_speech": round(s["no_speech_prob"], 2),
             "compression": round(s["compression_ratio"], 2)} for s in r["segments"]]
    (d / "segments.json").write_text(json.dumps(segs))
    wav.unlink()
    return text, segs


def frames(d, duration):
    imgs = sorted(d.glob("img_*.jpg"))
    src = None if imgs else video_src(d)
    if not src:
        return imgs
    n = max(3, min(8, round(duration / 8)))
    out = []
    for i in range(n):
        t = duration * (i + 0.5) / n
        f = d / f"frame_{i}.jpg"
        if not f.exists():   # -ss before -i seeks without reading the whole stream
            sh("ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=720:-2", str(f))
        out.append(f)
    return out


_ocr = None
def ocr(paths):
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    lines, seen = [], set()
    for p in paths:
        res, _ = _ocr(str(p))
        for _box, text, score in res or []:
            key = re.sub(r"\W", "", text.lower())
            if float(score) >= 0.6 and len(key) > 2 and key not in seen:   # subtitles repeat
                seen.add(key)
                lines.append(text)
    return lines


def gh_repo(slug):
    r = subprocess.run(["gh", "api", f"repos/{slug}", "--jq",
                        "{full_name,html_url,stars:.stargazers_count,description,archived,pushed_at,license:.license.spdx_id}"],
                       capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def needs_verification(brief) -> bool:
    """Decide whether this reel's transcript is worth a Sonnet `transcript-verifier` call.
    Inputs available: brief["segments"] (each has logprob, no_speech, compression),
    brief["transcript"], brief["ocr"] (deduped on-screen lines), brief["caption"],
    brief["duration_s"]. Return True to spend the call, False to trust Whisper.
    """
    # TODO(human): replace this always-on default with a real trigger.
    return True


def build(d, collection):
    meta = json.loads((d / "meta.json").read_text())
    dur = float(meta.get("video_duration") or 0)
    if (d / "segments.json").exists():                       # resume without re-transcribing
        text, segs = (d / "transcript.txt").read_text(), json.loads((d / "segments.json").read_text())
    else:
        text, segs = transcribe(d)
    shots = frames(d, dur)
    ocr_lines = ocr(shots)
    (d / "ocr.txt").write_text("\n".join(ocr_lines))
    caption = (meta.get("caption") or {}).get("text") or ""
    blob = "\n".join([caption, text, *ocr_lines])

    urls = sorted(set(URL_RE.findall(blob)))
    slugs = set(GH_RE.findall(blob)) | {s for s in SLUG_RE.findall("\n".join(ocr_lines))
                                        if not re.match(r"^\d+/\d+$", s)}
    repos = [r for s in sorted(slugs) if (r := gh_repo(s.rstrip(".")))]
    (d / "repos.json").write_text(json.dumps(repos, indent=1))

    music = (meta.get("clips_metadata") or {}).get("music_info") or {}
    brief = {
        "code": meta["code"], "collection": collection,
        "creator": "@" + meta["user"]["username"], "creator_name": meta["user"].get("full_name"),
        "posted": datetime.fromtimestamp(meta["taken_at"], timezone.utc).strftime("%Y-%m-%d"),
        "duration_s": int(dur), "likes": meta.get("like_count"), "comments": meta.get("comment_count"),
        "music": (music.get("music_asset_info") or {}).get("title"),
        "is_video": bool(dur), "caption": caption, "transcript": text, "segments": segs,
        "ocr": ocr_lines[:80], "frames": [p.name for p in shots],
        "urls": urls, "verified_repos": repos,
        "has_resources": bool(RESOURCE_WORDS.search(blob)) or bool(urls),
    }
    brief["needs_verification"] = bool(text) and needs_verification(brief)
    (d / "brief.json").write_text(json.dumps(brief, indent=1, ensure_ascii=False))
    return brief


if __name__ == "__main__":
    collection = sys.argv[1]; allowed(collection)
    codes = json.loads((DATA / f"queue_{collection.replace(' ', '_')}.json").read_text())["codes"]
    summary = {"verify": [], "find_repos": [], "empty_transcript": [], "all": []}
    for code in codes:
        d = DATA / code
        if not (d / "meta.json").exists():
            continue
        b = json.loads((d / "brief.json").read_text()) if (d / "brief.json").exists() else build(d, collection)
        summary["all"].append(code)
        if b["needs_verification"]: summary["verify"].append(code)
        if b["has_resources"]: summary["find_repos"].append(code)
        if not b["transcript"]: summary["empty_transcript"].append(code)
        print(code, "verify" if b["needs_verification"] else "", "repos" if b["has_resources"] else "", flush=True)
    (DATA / f"work_{collection.replace(' ', '_')}.json").write_text(json.dumps(summary, indent=1))
    print({k: len(v) for k, v in summary.items()})
