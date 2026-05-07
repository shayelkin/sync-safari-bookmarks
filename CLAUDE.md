# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Two-way bookmark sync between Chrome (extension) and Safari (`~/Library/Safari/Bookmarks.plist`),
bridged by a Python native  messaging host. The host is launched by Chrome over stdio per the Chrome
native messaging protocol; there  is no long-running daemon.

## Commands

- Install Python deps: `uv sync`
- Run tests: `uv run pytest`
- Single test: `uv run pytest tests/test_sync.py::test_idempotent`
- Type check: `uv run ty check`. Always run this in addition to the tests after changing
  Python code; passing tests do not imply a clean type check.
- Coverage: `uv run --with pytest-cov pytest --cov=host --cov-report=term-missing`. When
  adding or modifying code, aim for maximal coverage — add tests for new branches and for
  any uncovered lines you introduce. Defensive branches with no realistic trigger
  (e.g. `__eq__` returning `NotImplemented`, `except` blocks for impossible OS errors) are
  acceptable to leave uncovered; everything else should be exercised.
- Install native host manifest (after loading the unpacked extension at `chrome://extensions` to
  obtain its ID): `./install.sh  <chrome-extension-id>`. This writes
  `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.shayelkin.sync_safari_bookmarks.json`
  pointing at `host/run.sh`, which execs `.venv/bin/python -m host.main`.

The Chrome extension lives in `extension/` and is loaded as an unpacked MV3 extension;
`extension/manifest.json` is the entry point.

## Architecture

Three components, each with a clear seam, communicating only via well-defined data shapes:

1. **Chrome extension (`extension/`)** -- `sync.js` converts Chrome's tree to the canonical shape
   (`{bookmark_bar, other}` with `{type, title, url, date}` / `{type, title, children}` nodes),
   sends `{action: "sync", chrome_bookmarks}` via `chrome.runtime.sendNativeMessage`, then **blows
   away and recreates** Chrome's `bookmark_bar` (id `1`) and `other_bookmarks` (id `2`) subtrees
   from `response.merged`. Mobile bookmarks (id `3`) are ignored.
2. **Native host (`host/`)** -- `main.py` is the stdio entry point. `protocol.py` implements
   Chrome's length-prefixed (4-byte little-endian) JSON framing with a 1 MiB
   cap. `safari_bookmarks.py` reads/writes `Bookmarks.plist` via `plistlib`. `BookmarksBar`
   (Favorites) ↔ `bookmark_bar`. Chrome's "Other Bookmarks" maps to the user's items at the **plist
   root** — siblings of `BookmarksBar`, not children of any wrapper container — excluding presets:
   `BookmarksBar` itself, Reading List (`WebBookmarkIdentifier == "com.apple.ReadingList"`), and
   tab-group/History proxies (`WebBookmarkType == "WebBookmarkTypeProxy"`). Writes preserve those
   presets in place, replace BookmarksBar's children, and replace the user's root siblings with the
   merged `other` list (atomic via temp file + `os.rename`). `sync.py` holds the merge algorithm and
   the `Bookmark` / `Folder` dataclasses (note: `Bookmark.__eq__`/`__hash__` are by URL; `Folder` by
   title — these identities drive the merge).
3. **Persistent state** --  `~/.local/share/sync-safari-bookmarks/state.json` stores the last merged
   tree. Without it, merges are pure unions and cannot detect deletions.

### Merge algorithm (`host/sync.py`)

`merge_trees(chrome, safari, previous=None) -> (merged, deleted)` recurses through folders (matched
by title) and bookmarks (matched by URL):

- Bookmark on **both** sides → keep the one with the later `date`.
- Bookmark on **one** side only:
  - If present in `previous`: it was deleted on the other side → drop from merged, append to `deleted`.
  - If not in `previous`: new addition → keep.
- Folders are merged recursively; duplicate-titled folders at the same level have their children combined.

Deleted bookmarks are surfaced to the user by writing them into a `Recently Deleted Bookmarks`
folder under Safari's `other` (Bookmarks Menu) — see `_handle_sync` in `host/main.py`. They are
intentionally not returned to Chrome's tree.

The merge must satisfy the properties tested in `tests/test_sync.py`: idempotent, commutative on
URLs, superset of inputs without previous state, and zero deletions without previous state. Changes
to the merge logic should preserve these.

### Data shape (canonical, on the wire)

```jsonc
{ "bookmark_bar": [ ... ], "other": [ ... ] }
// item: {"type":"bookmark","title":"...","url":"...","date":"<iso8601>"}
// item: {"type":"folder","title":"...","children":[...]}
```

The host responds with `{status, merged, stats}` or `{status:"error", error}`; the extension applies
`merged` back to Chrome.
