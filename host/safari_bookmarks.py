"""Read and write Safari's Bookmarks.plist, converting to/from canonical format."""

from __future__ import annotations

import os
import plistlib
import tempfile
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from host.sync import Bookmark, BookmarkItem, Folder

BOOKMARKS_PLIST = Path.home() / "Library" / "Safari" / "Bookmarks.plist"

# Safari's Favorites bar.
_BOOKMARKS_BAR_TITLE = "BookmarksBar"

# Real Safari preset markers — entries we preserve untouched on write.
_PRESET_IDENTIFIERS = {"com.apple.ReadingList"}
_PRESET_TYPES = {"WebBookmarkTypeProxy"}  # tab groups, History, etc.

# Titles of legitimate Safari containers that lack a strong identifier marker.
# Existing root entries with these titles are preserved in place on write.
_PRESERVE_TITLES = frozenset({"BookmarksMenu"})

# Titles we recognize as Safari-internal but do not preserve. Existing root
# entries with these titles are dropped on write — they are bogus folders
# created by prior sync bugs (e.g. a "com.apple.ReadingList" folder serialized
# from Chrome content because the real preset was misread).
_DROP_TITLES = frozenset({"com.apple.ReadingList"})

# Combined set: never surfaced as user content on read, never written into
# Safari from merged `other` content.
PRESET_TITLES = _PRESERVE_TITLES | _DROP_TITLES


def _is_safari_preset(child: dict) -> bool:
    """True for real Safari preset entries, identified by strong markers."""
    if child.get("WebBookmarkType") in _PRESET_TYPES:
        return True
    if child.get("WebBookmarkIdentifier") in _PRESET_IDENTIFIERS:
        return True
    return False


def strip_preset_lookalikes(
    items: list[BookmarkItem],
) -> list[BookmarkItem]:
    """Drop top-level folders whose title clashes with a Safari preset."""
    return [
        i for i in items
        if not (isinstance(i, Folder) and i.title in PRESET_TITLES)
    ]


def read(path: Path = BOOKMARKS_PLIST) -> dict[str, list[BookmarkItem]]:
    """Read Safari bookmarks, returning {bookmark_bar, other}.

    `bookmark_bar` is the children of Safari's BookmarksBar (Favorites).
    `other` is everything else at the plist root — sibling folders/bookmarks
    of BookmarksBar — excluding presets like Reading List and tab groups.
    """
    with open(path, "rb") as f:
        plist = plistlib.load(f)

    bookmark_bar: list[BookmarkItem] = []
    other_entries: list[dict] = []
    for child in plist.get("Children", []):
        if _is_safari_preset(child):
            continue
        title = child.get("Title", "")
        if title == _BOOKMARKS_BAR_TITLE:
            bookmark_bar = _parse_children(child.get("Children", []))
            continue
        # Defense: an identifier-less entry titled like a preset is either an
        # obscure plist variant or a bogus folder from a prior bad write —
        # don't surface it as user content.
        if title in PRESET_TITLES:
            continue
        other_entries.append(child)

    return {"bookmark_bar": bookmark_bar, "other": _parse_children(other_entries)}


def _parse_children(children: list[dict]) -> list[BookmarkItem]:
    items: list[BookmarkItem] = []
    for entry in children:
        wbt = entry.get("WebBookmarkType", "")
        if wbt == "WebBookmarkTypeLeaf":
            uri_dict = entry.get("URIDictionary", {})
            title = uri_dict.get("title", entry.get("Title", ""))
            url = entry.get("URLString", "")
            if url:
                items.append(Bookmark(
                    title=title,
                    url=url,
                    date=_parse_date(entry),
                ))
        elif wbt == "WebBookmarkTypeList":
            items.append(Folder(
                title=entry.get("Title", "Untitled"),
                children=_parse_children(entry.get("Children", [])),
            ))
    return items


def _parse_date(entry: dict) -> datetime:
    """Extract a usable date from a plist entry, falling back to now."""
    # Safari doesn't store dates in a consistent way; use current time as fallback.
    return datetime.now(timezone.utc)


def write(
    roots: dict[str, list[BookmarkItem]],
    path: Path = BOOKMARKS_PLIST,
) -> None:
    """Write merged bookmarks back to Safari's plist.

    Replaces BookmarksBar's children with `bookmark_bar`, replaces the
    user's root-level siblings of BookmarksBar with `other` (preserving
    presets like Reading List and tab-group proxies in place), and writes
    atomically.
    """
    with open(path, "rb") as f:
        plist = plistlib.load(f)

    bar_serialized = _serialize_children(roots.get("bookmark_bar", []))
    other_serialized = _serialize_children(
        strip_preset_lookalikes(roots.get("other", []))
    )

    new_children: list[dict] = []
    other_inserted = False
    for child in plist.get("Children", []):
        if _is_safari_preset(child):
            new_children.append(child)
            continue
        title = child.get("Title", "")
        if title == _BOOKMARKS_BAR_TITLE:
            child = dict(child)
            child["Children"] = bar_serialized
            new_children.append(child)
            continue
        if title in _PRESERVE_TITLES:
            new_children.append(child)
            continue
        # Any other root entry — including bogus _DROP_TITLES folders from
        # prior writes — is replaced by the merged `other` list.
        if not other_inserted:
            new_children.extend(other_serialized)
            other_inserted = True

    if not other_inserted:
        new_children.extend(other_serialized)

    plist["Children"] = new_children

    # Atomic write: temp file + rename.
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=".bookmarks_", suffix=".plist"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            plistlib.dump(plist, f, fmt=plistlib.FMT_BINARY)
        os.rename(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _serialize_children(items: Sequence[BookmarkItem]) -> list[dict]:
    result: list[dict] = []
    for item in items:
        if isinstance(item, Bookmark):
            result.append({
                "WebBookmarkType": "WebBookmarkTypeLeaf",
                "WebBookmarkUUID": str(uuid.uuid4()).upper(),
                "URLString": item.url,
                "URIDictionary": {"title": item.title},
            })
        elif isinstance(item, Folder):
            result.append({
                "WebBookmarkType": "WebBookmarkTypeList",
                "WebBookmarkUUID": str(uuid.uuid4()).upper(),
                "Title": item.title,
                "Children": _serialize_children(item.children),
            })
    return result
