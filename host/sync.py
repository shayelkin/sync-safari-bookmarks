# SPDX-License-Identifier: MIT
"""Union merge of bookmark trees from Chrome and Safari."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Bookmark:
    title: str
    url: str
    date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Bookmark):
            return NotImplemented
        return self.url == other.url

    def __hash__(self) -> int:
        return hash(self.url)


@dataclass
class Folder:
    title: str
    children: list[BookmarkItem] = field(default_factory=list)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Folder):
            return NotImplemented
        return self.title == other.title

    def __hash__(self) -> int:
        return hash(self.title)


type BookmarkItem = Folder | Bookmark


def merge_trees(
    chrome: list[BookmarkItem],
    safari: list[BookmarkItem],
    previous: list[BookmarkItem] | None = None,
) -> tuple[list[BookmarkItem], list[Bookmark]]:
    """Merge two bookmark lists, returning (merged, deleted).

    `previous` is the last-known merged state. If a bookmark was in `previous`
    but is missing from one side, it was intentionally deleted — remove it from
    both sides and add it to the deleted list.

    Without `previous`, this is a pure union merge (no deletions detected).
    """
    deleted: list[Bookmark] = []
    merged = _merge_children(chrome, safari, previous, deleted)
    return merged, deleted


def _merge_children(
    a: list[BookmarkItem],
    b: list[BookmarkItem],
    prev: list[BookmarkItem] | None,
    deleted: list[Bookmark],
) -> list[BookmarkItem]:
    prev_folders = _folder_index(prev) if prev else {}
    prev_bookmarks = _bookmark_index(prev) if prev else {}

    a_folders = _folder_index(a)
    b_folders = _folder_index(b)
    a_bookmarks = _bookmark_index(a)
    b_bookmarks = _bookmark_index(b)

    result: list[BookmarkItem] = []

    # Merge folders: present in either side
    all_folder_titles = list(dict.fromkeys(
        [f.title for f in a_folders.values()]
        + [f.title for f in b_folders.values()]
    ))
    for title in all_folder_titles:
        fa = a_folders.get(title)
        fb = b_folders.get(title)
        fp = prev_folders.get(title)
        merged_folder = Folder(
            title=title,
            children=_merge_children(
                fa.children if fa else [],
                fb.children if fb else [],
                fp.children if fp else None,
                deleted,
            ),
        )
        result.append(merged_folder)

    # Merge bookmarks by URL
    all_urls = list(dict.fromkeys(
        list(a_bookmarks.keys()) + list(b_bookmarks.keys())
    ))
    for url in all_urls:
        ba = a_bookmarks.get(url)
        bb = b_bookmarks.get(url)
        bp = prev_bookmarks.get(url)

        in_a = ba is not None
        in_b = bb is not None
        in_prev = bp is not None

        if in_a and in_b:
            # Present on both sides — keep the one with the later date
            result.append(ba if ba.date >= bb.date else bb)
        elif in_a and not in_b:
            if in_prev:
                # Was in previous merged state and removed from b → deleted
                deleted.append(ba)
            else:
                # New on a's side
                result.append(ba)
        elif not in_a and in_b:
            if in_prev:
                # Was in previous merged state and removed from a → deleted
                deleted.append(bb)
            else:
                # New on b's side
                result.append(bb)

    return result


def _folder_index(items: list[BookmarkItem] | None) -> dict[str, Folder]:
    if not items:
        return {}
    index: dict[str, Folder] = {}
    for item in items:
        if not isinstance(item, Folder):
            continue
        if item.title in index:
            # Merge children of duplicate-titled folders.
            index[item.title].children.extend(item.children)
        else:
            index[item.title] = Folder(item.title, list(item.children))
    return index


def _bookmark_index(items: list[BookmarkItem] | None) -> dict[str, Bookmark]:
    if not items:
        return {}
    return {item.url: item for item in items if isinstance(item, Bookmark)}


def bookmarkitem_to_dict(item: BookmarkItem) -> dict:
    if isinstance(item, Bookmark):
        return {
            "type": "bookmark",
            "title": item.title,
            "url": item.url,
            "date": item.date.isoformat(),
        }
    return {
        "type": "folder",
        "title": item.title,
        "children": [bookmarkitem_to_dict(c) for c in item.children],
    }


def bookmarkitem_from_dict(d: dict) -> BookmarkItem:
    if d["type"] == "bookmark":
        return Bookmark(
            title=d["title"],
            url=d["url"],
            date=datetime.fromisoformat(d["date"]),
        )
    return Folder(
        title=d["title"],
        children=[bookmarkitem_from_dict(c) for c in d.get("children", [])],
    )


