"""Shared settings, loaded from config.yaml (path in $REEL_CONFIG, else <repo>/config.yaml).
Copy config.example.yaml to config.yaml to start. Every script imports from here."""
import os
import re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("REEL_CONFIG", ROOT / "config.yaml")).expanduser()
if not CONFIG_PATH.exists():
    raise SystemExit(f"No config at {CONFIG_PATH}. Copy config.example.yaml to config.yaml and fill it in.")
CFG = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def _path(key, default):
    return Path(os.path.expanduser(str(CFG.get(key) or default)))


VAULT = _path("vault", "~/Documents/Vaults/IG Reels")
SYNC = VAULT / ".sync.json"
DATA = Path(os.environ.get("REEL_DATA") or _path("data_dir", "~/reel-pipeline/data")).expanduser()  # outside the vault
PROFILE = _path("browser_profile", "~/reel-pipeline/browser-profile")                              # persistent IG login

INSTAGRAM_USER = CFG.get("instagram_user") or ""
COLLECTIONS = dict(CFG.get("collections") or {})
BLOCKED = set(CFG.get("blocked") or [])

# For people who never sort saves into collections: ingest the whole "All posts" saved feed
# as one pseudo-collection. The categorizer sorts every reel into topics and playbooks anyway,
# so nothing depends on how (or whether) you organized them on Instagram.
ALL_SAVED = "all saved"
INGEST_ALL_SAVED = bool(CFG.get("ingest_all_saved", False)) and not ({"all-posts", ALL_SAVED} & BLOCKED)
if INGEST_ALL_SAVED and INSTAGRAM_USER:
    COLLECTIONS.setdefault(ALL_SAVED, f"https://www.instagram.com/{INSTAGRAM_USER}/saved/all-posts/")

IG_APP_ID = "936619743392459"                     # Instagram web app id, same for everyone
REQUEST_GAP_S = float(CFG.get("rate_limit_s", 1.0))
MAX_NEW_PER_RUN = int(CFG.get("max_new_per_run", 100))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL") or CFG.get("whisper_model") or "mlx-community/whisper-large-v3-turbo"

TOPIC_DESCRIPTIONS = dict(CFG.get("topics") or {"Misc": "nothing to act on"})
TOPICS = list(TOPIC_DESCRIPTIONS)                 # topics approved later also live in <vault>/Topics/
USER_PROFILE = (CFG.get("profile") or "").strip()
RELEVANCE = (CFG.get("relevance") or "3 = useful now; 2 = useful later; 1 = little value").strip()

EFFORTS = ["5 min", "1 hour", "weekend", "ongoing"]


def allowed(collection: str) -> None:
    if collection == ALL_SAVED and not INGEST_ALL_SAVED:
        raise SystemExit(f"'{ALL_SAVED}' is off. Set `ingest_all_saved: true` in {CONFIG_PATH.name} "
                         f"(and keep `all-posts` out of `blocked:`) to ingest every saved post.")
    if collection in BLOCKED or collection not in COLLECTIONS:
        raise SystemExit(f"'{collection}' is not an allowed collection (add it under `collections:` in "
                         f"{CONFIG_PATH.name}, and keep it out of `blocked:`)")


def code_dir(code: str) -> Path:
    # Shortcodes become folder names, so allow only Instagram's alphabet (no '/', no '..').
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,40}", code or ""):
        raise SystemExit(f"Refusing unexpected shortcode {code!r}")
    d = DATA / code
    d.mkdir(parents=True, exist_ok=True)
    return d
