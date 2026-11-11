"""Helpers shared by ig.py and process.py: picking streams out of an Instagram media item."""
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

CDN_HOSTS = (".cdninstagram.com", ".fbcdn.net")
# ffmpeg protocols allowed when reading a URL: no file:, concat:, pipe: or other local readers.
FFMPEG_PROTOCOLS = "https,tls,tcp"


def safe_cdn(url):
    """Return url only if it is https on Instagram's CDN; anything else is dropped."""
    try:
        p = urlparse(url or "")
    except ValueError:
        return None
    return url if p.scheme == "https" and (p.hostname or "").endswith(CDN_HOSTS) else None


def pick_streams(mpd: str):
    """Return (audio_url, video_url) from a DASH manifest: the audio track, and the
    lowest-bandwidth video at least 480 px wide."""
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


def streams(item: dict):
    """(audio_url, video_url) for any media item; either may be None (photos, carousels)."""
    if item.get("video_dash_manifest"):
        a, v = pick_streams(item["video_dash_manifest"])
        return safe_cdn(a), safe_cdn(v)
    if item.get("video_versions"):
        return None, safe_cdn(min(item["video_versions"], key=lambda x: x.get("width", 9999))["url"])
    return None, None
