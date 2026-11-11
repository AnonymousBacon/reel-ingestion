"""Steps 7-10: everything that touches the vault. Deterministic, no LLM tokens.

  python vault.py init                 # create the vault skeleton from template/ (never overwrites)
  python vault.py context              # -> data/vault_context.json (profile, topics, tools, titles) for agents
  python vault.py render "cool cs"     # note.json -> Reels/*.md, Topics, Tools, Collections, Start here, .sync.json
  python vault.py verify               # wikilinks, YAML, topic list

Never overwrites an existing reel note and never deletes anything (hard rule 3).
"""
import json, re, shutil, sys
from datetime import date
from pathlib import Path
import yaml
from config import (VAULT, SYNC, DATA, ROOT, TOPICS, TOPIC_DESCRIPTIONS, EFFORTS, COLLECTIONS,
                    USER_PROFILE, RELEVANCE, allowed)

REELS, TOPIC_DIR, TOOL_DIR, COLL_DIR, PATHS = (VAULT / x for x in ("Reels", "Topics", "Tools", "Collections", "Paths"))
HUB = VAULT / "Playbooks.md"
LINK_RE = re.compile(r"\[\[([^\]|#]+)")
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
REQUIRED = ["type", "what", "creator", "url", "collection", "topics", "relevance",
            "effort", "status", "cost", "posted", "duration_s", "code"]


# ---------- helpers ----------
def front(p: Path):
    s = p.read_text(encoding="utf-8")
    if not s.startswith("---\n"):
        return {}, s
    head, body = s[4:].split("\n---\n", 1)
    return yaml.safe_load(head) or {}, body


def strip_link(x):  # "[[Topic]]" -> "Topic"
    return x.strip("[]") if isinstance(x, str) else x


def all_topics():
    return sorted(set(TOPICS) | {p.stem for p in TOPIC_DIR.glob("*.md")})


def reel_index():
    """{title: frontmatter} for every reel note."""
    return {p.stem: front(p)[0] for p in REELS.glob("*.md")}


def safe_title(t):
    t = t.replace("/", "-")
    t = re.sub(r'[\\:*?"<>|#^\[\]]', "", t).strip()
    return t[:60].rstrip()


def inert(text):
    """Make stranger-written text display-only in Obsidian: no raw HTML (e.g. a tracking
    <img>, <iframe>), no wikilinks or embeds that add fake graph edges, no code blocks
    that a plugin like Dataview or Templater could run."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("[[", "\\[\\[").replace("![", "!\\[").replace("```", "ʼʼʼ"))


def quote(text):
    return "\n".join("> " + inert(ln) if ln.strip() else ">" for ln in text.strip().splitlines()) or "> (empty)"


def bullets(items):
    return "\n".join(f"- {x}" for x in items)


def upsert_list(note: Path, header_md: str, entries: dict, sort_key=None):
    """Merge `entries` {title: line} into the '## Reels' list of `note`, keeping other text."""
    text = note.read_text(encoding="utf-8") if note.exists() else header_md
    if "## Reels" not in text:
        text = text.rstrip() + "\n\n## Reels\n"
    before, after = text.split("## Reels", 1)
    lines = after.lstrip("\n").splitlines()
    items = [l for l in lines if l.startswith("- [[")]
    rest = [l for l in lines if not l.startswith("- [[")]
    have = {LINK_RE.search(l).group(1) for l in items}
    items += [line for t, line in entries.items() if t not in have]
    if sort_key:
        items.sort(key=lambda l: sort_key(LINK_RE.search(l).group(1)))   # stable: keeps prior order
    note.write_text(before + "## Reels\n" + "\n".join(items) + "\n" + ("\n".join(rest) + "\n" if rest else ""),
                    encoding="utf-8")


# ---------- playbooks ----------
def playbooks():
    """{name: goal} for every note in Paths/ with `type: playbook`."""
    out = {}
    for p in PATHS.glob("*.md"):
        fm, _ = front(p)
        if fm.get("type") == "playbook":
            out[p.stem] = fm.get("goal", "")
    return out


def add_line(text, header, line, before=("## Skip", "## Sources")):
    """Append `line` to the end of section `header`; create the section (above `before`) if missing."""
    if header in text:
        start = text.index(header) + len(header)
        nxt = text.find("\n## ", start)
        head, rest = (text, "") if nxt == -1 else (text[:nxt], text[nxt:])
        return head.rstrip("\n") + "\n" + line + "\n" + ("\n" + rest.lstrip("\n") if rest else "")
    cuts = [i for h in before if (i := text.find("\n" + h)) != -1]
    if cuts:
        i = min(cuts)
        return text[:i].rstrip("\n") + f"\n\n{header}\n{line}\n\n" + text[i:].lstrip("\n")
    return text.rstrip("\n") + f"\n\n{header}\n{line}\n"


def append_inline(text, header, link):
    """Add ' · [[X]]' to the one-line list under `header` (Sources, Nothing to act on)."""
    m = re.search(re.escape(header) + r"\n(.*)", text)
    if m and m.group(1).strip():
        return text[:m.end()] + " · " + link + text[m.end():]
    return add_line(text, header, link, before=())


def file_in_playbook(name, reel, step, skip):
    """New steps land in '## New from reels' so existing, hand-ordered steps are never rewritten."""
    p = PATHS / f"{name}.md"
    t = p.read_text(encoding="utf-8")
    link = f"[[{reel}]]"
    t = add_line(t, "## Skip", f"- {link}: {skip}", before=("## Sources",)) if skip else \
        add_line(t, "## New from reels", f"- [ ] {step} → {link}")
    t = append_inline(t, "## Sources", link)
    t = re.sub(r"^reels: (\d+)$", lambda m: f"reels: {int(m.group(1)) + 1}", t, count=1, flags=re.M)
    p.write_text(t, encoding="utf-8")
    if HUB.exists():   # keep the hub table's count in step
        h = HUB.read_text(encoding="utf-8")
        h = re.sub(r"(\| \[\[" + re.escape(name) + r"\]\] \|.*\| )(\d+)( \|)",
                   lambda m: f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}", h, count=1)
        HUB.write_text(h, encoding="utf-8")


# ---------- init ----------
def cmd_init():
    """Create the vault skeleton. Existing files are left untouched."""
    made = []
    def put(path: Path, text=None, src=None):
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, path) if src else path.write_text(text, encoding="utf-8")
        made.append(str(path.relative_to(VAULT)))
    for src in (ROOT / "template").rglob("*"):
        if src.is_file() and src.name != ".DS_Store":
            put(VAULT / src.relative_to(ROOT / "template"), src=src)
    for d in ("Reels", "Topics", "Tools", "Collections", "Paths"):
        (VAULT / d).mkdir(parents=True, exist_ok=True)
    for name, desc in TOPIC_DESCRIPTIONS.items():
        put(TOPIC_DIR / f"{name}.md", f"---\ntype: topic\n---\n# {name}\n\n{desc}\n\n## Reels\n")
    put(SYNC, json.dumps({"scope": "saved reels only; collections: " + ", ".join(COLLECTIONS), "synced": {}}, indent=1))
    print(f"vault: {VAULT}\ncreated {len(made)} files" + "".join(f"\n  {m}" for m in made))


# ---------- context ----------
def cmd_context():
    ctx = {
        "profile": USER_PROFILE,
        "relevance": RELEVANCE,
        "topic_descriptions": {t: TOPIC_DESCRIPTIONS.get(t, "") for t in all_topics()},
        "topics": all_topics(),
        "efforts": EFFORTS,
        "tools": {p.stem: next((l for l in p.read_text().splitlines() if l.startswith("**Repo:**")), "")
                  for p in TOOL_DIR.glob("*.md")},
        "existing_titles": sorted(p.stem for p in REELS.glob("*.md")),
        "playbooks": playbooks(),
        "vault": str(VAULT),
    }
    out = DATA / "vault_context.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ctx, indent=1, ensure_ascii=False))
    print(out)


# ---------- render ----------
def norm_url(u):
    """Compare URLs without the noise text adds: trailing punctuation, '.git', a final '/'."""
    u = u.rstrip(".,;:!?)]}'\"")
    u = u[:-4] if u.endswith(".git") else u
    return u.rstrip("/")


def render_note(b, n, corr, allowed_urls, dropped):
    ok = {norm_url(a) for a in allowed_urls}

    def clean(s):  # rule 4: remove any URL that no source backs up
        for u in URL_RE.findall(s):
            if norm_url(u) not in ok:
                dropped.append(u); s = s.replace(u, "(link not verified)")
        return s

    links = [l for l in n.get("links", []) if norm_url(l["url"]) in ok]
    dropped += [l["url"] for l in n.get("links", []) if norm_url(l["url"]) not in ok]
    repos = sorted({l["url"] for l in links if re.match(r"https://github\.com/[^/]+/[^/]+/?$", l["url"])})
    tools = [t for t in n.get("tools", []) if (TOOL_DIR / f"{t}.md").exists()]

    fm = {"type": "reel", "what": n["what"], "creator": b["creator"],
          "url": f"https://www.instagram.com/reel/{b['code']}/"}
    if repos: fm["repo"] = repos[0] if len(repos) == 1 else repos
    fm |= {"collection": b["collection"], "topics": [f"[[{t}]]" for t in n["topics"]]}
    if tools: fm["tools"] = [f"[[{t}]]" for t in tools]
    if n.get("playbook"): fm["playbook"] = f"[[{n['playbook']}]]"
    fm |= {"relevance": int(n["relevance"]), "effort": n["effort"], "status": "inbox",
           "cost": n.get("cost", "free"), "posted": b["posted"], "duration_s": b["duration_s"], "code": b["code"]}

    sc = n.get("showcasing", {})
    rows = "\n".join(f"| **{k.title()}** | {clean(sc[k])} |" for k in ("what", "who", "when", "where", "why") if sc.get(k))
    parts = [f"---\n{yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)}---\n", f"# {n['title']}\n"]
    if repos:
        parts.append("**Repo:** " + " · ".join(f"[{u[19:]}]({u})" for u in repos) + "\n")
    parts += [f"> **TL;DR:** {clean(n['tldr'])}\n", f"## What it's showcasing\n| | |\n|---|---|\n{rows}\n",
              f"## For you\n{bullets(clean(x) for x in n['for_you'])}\n"]
    link_lines = [f"{l['name']} — {l['url']}" for l in links] + [f"Not found: {m}" for m in n.get("missing", [])]
    if link_lines: parts.append("## Links & exact names\n" + bullets(link_lines) + "\n")
    for key, head in (("setup", "Setup"), ("watch_out", "Watch out"), ("on_screen", "On screen")):
        if n.get(key):
            body = "\n".join(f"{i}. {clean(x)}" for i, x in enumerate(n[key], 1)) if key == "setup" \
                else bullets(clean(x) for x in n[key])
            parts.append(f"## {head}\n{body}\n")
    if b["caption"]:
        parts.append("> [!quote]- Caption\n" + quote(b["caption"]) + "\n")
    tx = b["transcript"]
    for f in corr.get("fixes", []):          # agent returns small {heard, actual, source} diffs, not a rewrite
        tx = tx.replace(f["heard"], f["actual"])
    notes = "".join(f"> *Correction: Whisper heard \"{f['heard']}\"; changed to \"{f['actual']}\" "
                    f"(from the {f.get('source', 'screen')}).*\n>\n" for f in corr.get("fixes", []))
    parts.append("> [!quote]- Transcript (Whisper)\n" + notes +
                 (quote(tx) if tx else "> (no speech; music-only reel)") + "\n")
    return fm, "\n".join(parts)


def cmd_render(collection):
    allowed(collection)
    work = json.loads((DATA / f"work_{collection.replace(' ', '_')}.json").read_text())
    idx = reel_index()
    codes_in_vault = {fm.get("code") for fm in idx.values()}
    topics_ok = set(all_topics())
    books = playbooks()
    report = {"added": [], "skipped_existing": [], "dropped_urls": {}, "proposed_topics": {},
              "proposed_playbooks": {}, "playbook_steps": {}, "empty_transcript": work.get("empty_transcript", []),
              "tools_needing_notes": [], "not_ready": []}
    mentions_p = DATA / "tool_mentions.json"
    mentions = json.loads(mentions_p.read_text()) if mentions_p.exists() else {}
    new, drafts = {}, {}   # title -> fm, title -> note.json

    for code in work["all"]:
        d = DATA / code
        if code in codes_in_vault:
            report["skipped_existing"].append(code); continue
        if not (d / "note.json").exists():
            report["not_ready"].append(code); continue
        b = json.loads((d / "brief.json").read_text())
        n = json.loads((d / "note.json").read_text())
        corr = json.loads((d / "corrections.json").read_text()) if (d / "corrections.json").exists() else {}
        found = json.loads((d / "links.json").read_text()) if (d / "links.json").exists() else {}
        allowed_urls = set(b["urls"]) | {r["html_url"] for r in b["verified_repos"]} | \
                       {l["url"] for l in found.get("links", [])}

        bad = [t for t in n["topics"] if t not in topics_ok]
        for t in bad: report["proposed_topics"].setdefault(t, []).append(code)
        n["topics"] = [t for t in n["topics"] if t in topics_ok] or ["Misc"]
        for t in n.get("tools", []):
            mentions.setdefault(t, [])
            if code not in mentions[t]: mentions[t].append(code)
        if n.get("playbook") not in books:      # unknown name -> proposal, like topics (3-reel rule)
            prop = n.get("proposed_playbook") or n.get("playbook")
            if prop: report["proposed_playbooks"].setdefault(prop, []).append(code)
            n["playbook"], n["_proposed"] = None, bool(prop)

        title = safe_title(n["title"]); base = title; k = 2
        while (REELS / f"{title}.md").exists() or title in new:
            title = f"{base} ({k})"; k += 1
        n["title"] = title
        dropped = []
        fm, md = render_note(b, n, corr, allowed_urls, dropped)
        (REELS / f"{title}.md").write_text(md, encoding="utf-8")
        if dropped: report["dropped_urls"][title] = dropped
        new[title] = fm
        drafts[title] = n
        report["added"].append(title)

    mentions_p.write_text(json.dumps(mentions, indent=1))
    report["tools_needing_notes"] = [t for t, cs in mentions.items()
                                     if len(cs) >= 2 and not (TOOL_DIR / f"{t}.md").exists()]
    idx.update(new)
    rel = lambda t: -int((idx.get(t) or {}).get("relevance", 1))
    line = lambda t: f"- [[{t}]]: {idx[t]['what']}"

    for topic in all_topics():
        hits = {t: line(t) for t, fm in new.items() if f"[[{topic}]]" in fm["topics"]}
        if hits:
            upsert_list(TOPIC_DIR / f"{topic}.md", f"---\ntype: topic\n---\n# {topic}\n", hits, rel)
    for t, fm in new.items():
        for tool in fm.get("tools", []):
            upsert_list(TOOL_DIR / f"{strip_link(tool)}.md", "", {t: line(t)})
    for t, n in drafts.items():
        pb = n.get("playbook")
        if pb:
            file_in_playbook(pb, t, n.get("playbook_step") or n["what"], n.get("playbook_skip"))
            report["playbook_steps"].setdefault(pb, []).append(t)
        elif int(n["relevance"]) == 1 and HUB.exists() and not n.get("_proposed"):
            HUB.write_text(append_inline(HUB.read_text(encoding="utf-8"), "## Nothing to act on", f"[[{t}]]"),
                           encoding="utf-8")
    if new:
        upsert_list(COLL_DIR / f"{collection}.md",
                    f"---\ntype: collection\n---\n# {collection}\n\nInstagram: {COLLECTIONS[collection]}\n",
                    {t: line(t) for t in new})

    # .sync.json: append only (step 9)
    s = json.loads(SYNC.read_text())
    entry = s["synced"].setdefault(collection, {"date": "", "codes": []})
    entry["codes"] += [fm["code"] for fm in new.values() if fm["code"] not in entry["codes"]]
    entry["date"] = date.today().isoformat()
    SYNC.write_text(json.dumps(s, indent=1))

    # Start here: "Synced so far"
    sh = VAULT / "Start here.md"
    txt = sh.read_text(encoding="utf-8")
    counts = {c: sum(1 for fm in idx.values() if fm.get("collection") == c) for c in s["synced"]}
    lines = [f"- [[{c}]]: {counts[c]} reel{'s' * (counts[c] != 1)}, {date.fromisoformat(v['date']).strftime('%b %-d, %Y')}"
             for c, v in s["synced"].items()]
    todo = [c for c in COLLECTIONS if c not in s["synced"]]
    if todo: lines.append("- Still to do: " + ", ".join(todo))
    txt = re.sub(r"## Synced so far\n(?:- .*\n?)*", "## Synced so far\n" + "\n".join(lines) + "\n", txt)
    sh.write_text(txt, encoding="utf-8")

    (DATA / f"report_{collection.replace(' ', '_')}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in report.items()}))


# ---------- relink ----------
def cmd_relink(codes):
    """Re-render existing reel notes from their saved agent output (e.g. after a link-guard fix).
    Only touches notes still exactly as rendered: status inbox and the drafted relevance."""
    by_code = {fm.get("code"): t for t, fm in reel_index().items()}
    books = playbooks()
    for code in codes:
        d, title = DATA / code, by_code.get(code)
        if not title or not (d / "note.json").exists():
            print(f"{code}: no note or no saved draft, skipped"); continue
        n = json.loads((d / "note.json").read_text())
        fm_now = reel_index()[title]
        if fm_now.get("status") != "inbox" or fm_now.get("relevance") != int(n["relevance"]):
            print(f"{code}: edited by you, skipped"); continue
        b = json.loads((d / "brief.json").read_text())
        corr = json.loads((d / "corrections.json").read_text()) if (d / "corrections.json").exists() else {}
        found = json.loads((d / "links.json").read_text()) if (d / "links.json").exists() else {}
        allowed_urls = set(b["urls"]) | {r["html_url"] for r in b["verified_repos"]} | \
                       {l["url"] for l in found.get("links", [])}
        n["title"], n["topics"] = title, [strip_link(t) for t in fm_now["topics"]]
        n["playbook"] = n.get("playbook") if n.get("playbook") in books else None
        dropped = []
        _, md = render_note(b, n, corr, allowed_urls, dropped)
        (REELS / f"{title}.md").write_text(md, encoding="utf-8")
        print(f"{code}: {title}" + (f" (still unverified: {dropped})" if dropped else ""))


# ---------- verify ----------
def cmd_verify():
    names = {p.stem for p in VAULT.rglob("*") if p.is_file() and ".obsidian" not in p.parts} | \
            {p.name for p in VAULT.rglob("*.base")}
    problems = []
    for p in list(VAULT.rglob("*.md")) + list(VAULT.rglob("*.base")):
        if ".obsidian" in p.parts or p.name == "Welcome.md":
            continue
        text = re.sub(r"```.*?```|`[^`\n]*`", "", p.read_text(encoding="utf-8"), flags=re.S)  # code isn't linked
        for t in LINK_RE.findall(text):
            if t not in names:
                problems.append(f"broken link [[{t}]] in {p.relative_to(VAULT)}")
    topics = set(all_topics())
    for p in REELS.glob("*.md"):
        try:
            fm, _ = front(p)
        except Exception as e:
            problems.append(f"bad YAML in {p.name}: {e}"); continue
        miss = [k for k in REQUIRED if k not in fm]
        if miss: problems.append(f"{p.name}: missing {miss}")
        for t in fm.get("topics", []):
            if strip_link(t) not in topics: problems.append(f"{p.name}: unknown topic {t}")
        if fm.get("effort") not in EFFORTS: problems.append(f"{p.name}: effort {fm.get('effort')!r}")
        if fm.get("relevance") not in (1, 2, 3): problems.append(f"{p.name}: relevance {fm.get('relevance')!r}")
    print("\n".join(problems) or "vault OK")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    {"init": cmd_init, "context": cmd_context, "render": lambda: cmd_render(args[0]), "verify": cmd_verify,
     "relink": lambda: cmd_relink(args)}.get(
        cmd, lambda: print(__doc__))()
