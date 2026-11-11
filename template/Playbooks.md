---
type: index
---
# Playbooks

A playbook merges every reel on one goal into a single ordered checklist. Open one, do its
**Do this first** line, then work down. Open individual reels only when a step links to one.

New reels are filed automatically: the pipeline adds each one as a step under
`## New from reels` in the matching playbook. Move those steps into place when you review it.

To start a playbook, create `Paths/<Name>.md` with this frontmatter and add a row below:

```
---
type: playbook
goal: <the outcome, in one line>
reels: 0
---
```

| Playbook | Gets you | Reels |
|---|---|---|

## Nothing to act on
