---
type: index
---
# Glossary

Obsidian terms, each tied to how this vault uses it. Back to [[Start here]].

## The basics
- **Vault**: a normal folder of Markdown files that Obsidian opens. This one is `IG Reels/`. Nothing is locked in; you can open the files in any text editor.
- **Note**: one `.md` file. Here, one reel = one note.
- **Markdown**: plain-text formatting (`# heading`, `**bold**`, `- list`). Obsidian renders it for you.
- **Folder**: just a directory. This vault uses `Reels/`, `Topics/`, `Tools/`, `Collections/` and `Paths/`.
- **`.obsidian/`**: hidden folder holding your settings (graph colors, plugins). Don't edit by hand unless you know why.

## Linking
- **Wikilink** `[[Note name]]`: a link to another note, by name. Rename the note inside Obsidian and every link updates.
- **Alias link** `[[Note name|shown text]]`: same link, different display text. `[[Dashboard.base|Dashboard]]` shows "Dashboard".
- **Backlink**: a note that links *to* the one you're reading. Open the Backlinks panel on a Topic to see every reel filed under it.
- **Unlinked mention**: a place where a note's name appears as plain text without a link. Obsidian can offer to link it.
- **Embed** `![[Note]]`: shows another note's content inline, instead of just linking to it.
- **Heading link** `[[Note#Heading]]`: jumps to one section of a note.

## Metadata
- **Frontmatter**: the block between the `---` lines at the top of a note. It holds the note's data (`status`, `relevance`, `repo`…).
- **Properties**: Obsidian's friendly editor for frontmatter. Each field (`status`, `effort`, `cost`) is a property.
- **YAML**: the syntax inside frontmatter (`key: value`). A stray colon or bad indent breaks it.
- **Tag** `#tag`: a lightweight label. This vault uses topics and properties instead of tags.

## Views
- **Graph view**: a map where each note is a dot and each link is a line. Here: gold = Paths, blue = Topics, purple = Tools, green = relevance-3 reels.
- **Local graph**: the graph for just the open note and its neighbors. Much easier to read than the full graph.
- **Bases** (`.base` file): database-style views over your notes, with filters and columns. `Dashboard.base` is the table of reels with Quick wins, Worth trying, and so on.
- **Backlinks / Outgoing links panels**: right-sidebar lists of what links in and out of the current note.
- **Callout** `> [!quote]-`: a styled box. The trailing `-` makes it collapsed; the Caption and Transcript sections use this.

## How this vault is organized
- **Reel note**: one saved Instagram reel: summary, links, setup, caveats.
- **Topic note**: a hub for one subject (for example Security). Lists every reel on that subject, best first.
- **Tool note**: a hub for a tool that shows up in 2+ reels.
- **Collection note**: mirrors one Instagram saved collection.
- **Path**: an ordered plan built from reels, like a step-by-step study plan.
- **Playbook**: one note per goal that merges every reel on it into one ordered checklist. Each step links to its source reel. New reels land under *New from reels*.
- **Hub**: any note that mostly exists to link other notes (Topics, Tools, Collections).
- **Relevance (1–3)**: how much a reel applies to you now. 3 = act on it soon.
- **Status**: `inbox` (new), `try`, `tried`, `skip`.
- **Sync log** (`.sync.json`): the record of which reels have been ingested, so a re-run only picks up new ones.

## Handy shortcuts (Mac)
- `Cmd+O` quick switcher: jump to any note by name.
- `Cmd+P` command palette: run any command.
- `Cmd+Click` a link: open in a new tab.
- `Cmd+G` open the graph view.
