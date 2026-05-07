"""Native messaging host entry point.

Reads a sync request from Chrome, merges with Safari bookmarks,
writes the merged result to Safari's plist, and responds.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from host.protocol import read_message, write_message
from host.safari_bookmarks import (
    read as read_safari,
    strip_preset_lookalikes,
    write as write_safari,
)
from host.sync import (
    Bookmark,
    BookmarkItem,
    Folder,
    bookmarkitem_from_dict,
    bookmarkitem_to_dict,
    merge_trees,
)

STATE_FILE = Path.home() / ".local" / "share" / "sync-safari-bookmarks" / "state.json"
RECENTLY_DELETED_TITLE = "Recently Deleted Bookmarks"


def tree_to_dicts(items: list[BookmarkItem]) -> list[dict]:
    return [bookmarkitem_to_dict(item) for item in items]


def tree_from_dicts(dicts: list[dict]) -> list[BookmarkItem]:
    return [bookmarkitem_from_dict(d) for d in dicts]


def _load_previous_state() -> dict[str, list[BookmarkItem]] | None:
    if not STATE_FILE.exists():
        return None
    with open(STATE_FILE) as f:
        data = json.load(f)
    return {key: tree_from_dicts(val) for key, val in data.items()}


def _save_state(roots: dict[str, list[BookmarkItem]]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump({key: tree_to_dicts(val) for key, val in roots.items()}, f)


def _handle_sync(chrome_roots: dict[str, list[dict]]) -> dict:
    safari_roots = read_safari()
    previous = _load_previous_state()

    merged: dict[str, list[BookmarkItem]] = {}
    all_deleted: list[Bookmark] = []

    for root_name in ("bookmark_bar", "other"):
        chrome_items = tree_from_dicts(chrome_roots.get(root_name, []))
        safari_items = safari_roots.get(root_name, [])
        if root_name == "other":
            # Drop any preset-titled folder that leaked into Chrome from a
            # previous bad sync, so it doesn't propagate further.
            chrome_items = strip_preset_lookalikes(chrome_items)
            safari_items = strip_preset_lookalikes(safari_items)
        prev_items = previous.get(root_name) if previous else None
        m, d = merge_trees(chrome_items, safari_items, prev_items)
        merged[root_name] = m
        all_deleted.extend(d)

    # Put deleted bookmarks into a "Recently Deleted" folder in Safari's other bookmarks.
    if all_deleted:
        deleted_folder = Folder(RECENTLY_DELETED_TITLE, list(all_deleted))
        other = merged.get("other", [])
        # Replace existing deleted folder if present.
        other = [
            item for item in other
            if not (isinstance(item, Folder) and item.title == RECENTLY_DELETED_TITLE)
        ]
        other.append(deleted_folder)
        merged["other"] = other

    write_safari(merged)
    _save_state(merged)

    stats = {
        "deleted": len(all_deleted),
    }

    return {
        "status": "ok",
        "merged": {key: tree_to_dicts(val) for key, val in merged.items()},
        "stats": stats,
    }


def main() -> None:
    try:
        msg = read_message()
    except EOFError:
        sys.exit(0)

    action = msg.get("action")

    try:
        if action == "sync":
            response = _handle_sync(msg.get("chrome_bookmarks", {}))
        else:
            response = {"status": "error", "error": f"unknown action: {action}"}
    except Exception:
        response = {"status": "error", "error": traceback.format_exc()}

    write_message(response)


if __name__ == "__main__":
    main()
