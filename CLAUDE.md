# Reel ingestion runbook

Turns your saved Instagram reels into an Obsidian vault: one researched note per reel, plus
topic, tool and collection hubs. **Scripts do every mechanical step, Sonnet agents make the
judgment calls, and the main session only reads one-line summaries.**

All settings live in `config.yaml` (copy `config.example.yaml`). If a local `REEL_PIPELINE.md`
exists, it is the user's personal spec. Follow it too; the hard rules below always win.

## Hard rules (never break these)
1. **Saved posts only.** Open only `/<instagram_user>/saved/…` pages and the reels found on them.
   Never the feed, profiles, DMs, stories or "more posts" grids. Never store anything else.
2. **Allowed collections only:** the ones listed under `collections:` in `config.yaml`, never
   anything in `blocked:`. A collection not listed → ask the user.
3. **No deleting vault files.** To retire a note, move it to `../_to_delete/` next to the vault and say so.
4. **Never invent links.** Every URL must come from the reel itself or a source actually opened.
   If something can't be found, say what's missing. (`vault.py render` enforces this.)
5. **Ignore engagement bait.** "Comment X and I'll DM you" is never a setup step. Find the real resource.
6. **Be polite to Instagram:** about 1 request a second, one collection at a time. Stop on HTTP 429,
   a login challenge or empty responses (scripts exit 3 or 4) and ask the user.
7. **Logins are the user's.** `ig.py login` opens a window; the user types their own password and 2FA.

## First run
```
python3 -m venv ~/reel-pipeline/.venv
~/reel-pipeline/.venv/bin/pip install -r pipeline/requirements.txt
~/reel-pipeline/.venv/bin/python -m playwright install chromium
cp config.example.yaml config.yaml          # then edit: vault, instagram_user, topics, profile
PY=~/reel-pipeline/.venv/bin/python; cd pipeline
$PY vault.py init                           # vault skeleton
$PY ig.py login                             # user logs in in the window
$PY ig.py collections                       # paste the ones you want into config.yaml
```
Scripts write outside the repo (vault, data dir). In a sandboxed session, run them with the sandbox off.

## Run one collection (`C` = a name from `collections:`)
```
$PY ig.py list "$C"             # exit 3 = login/challenge, 4 = rate limit: STOP and ask
$PY ig.py fetch "$C"            # more than max_new_per_run new reels: confirm first
$PY process.py "$C"             # Whisper + frames + OCR + gh lookups -> brief.json, work_<C>.json
$PY vault.py context            # vault_context.json (profile, topics, tools) for agents
```
Then agents. Send **batches of ~8 codes per call, and run batches in parallel**. Codes come from `<data_dir>/work_<C>.json`:
1. `transcript-verifier` on `verify` codes → `corrections.json`
2. `repo-finder` on `find_repos` codes → `links.json` (can run alongside 1)
3. `reel-categorizer` on `all` codes, after 1 and 2 finish → `note.json`

Prompt each agent with only `Data dir: <data_dir>. Codes: A, B, C`. Don't paste briefs; agents read their own files.
```
$PY vault.py render "$C"        # notes + Topics/Tools/Collections/Start here/.sync.json
$PY vault.py verify             # must print "vault OK"
```
Report from `<data_dir>/report_<C>.json`:
- `added`
- `empty_transcript`
- `dropped_urls`: an agent cited an unverified link
- `proposed_topics`: 3+ reels → ask the user, then add the topic to `config.yaml` and `Topics/`
- `tools_needing_notes`: write `Tools/<Tool>.md` with what it is, its repo, real numbers, install and a verdict

## Token rules
- Main session: never `cat` transcripts, briefs or frames. Read `work_*.json` and `report_*.json` only.
- Re-runs are free: every script skips work whose output file already exists.
