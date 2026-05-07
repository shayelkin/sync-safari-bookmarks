"""Tests for Safari plist reading/writing."""

from __future__ import annotations

import plistlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from host.safari_bookmarks import (
    _parse_children,
    _serialize_children,
    read,
    strip_preset_lookalikes,
    write,
)
from host.sync import Bookmark, BookmarkItem, Folder


def _make_plist(bookmark_bar: list[dict] | None = None, other: list[dict] | None = None) -> bytes:
    """Build a minimal Safari Bookmarks.plist in memory.

    `other` entries are siblings of BookmarksBar at the plist root.
    """
    children = [
        {
            "WebBookmarkType": "WebBookmarkTypeProxy",
            "WebBookmarkIdentifier": "History",
            "Title": "History",
        },
        {
            "WebBookmarkType": "WebBookmarkTypeList",
            "Title": "BookmarksBar",
            "WebBookmarkUUID": "BAR-UUID",
            "Children": bookmark_bar or [],
        },
        *(other or []),
        {
            "WebBookmarkType": "WebBookmarkTypeList",
            "WebBookmarkIdentifier": "com.apple.ReadingList",
            "Title": "com.apple.ReadingList",
            "Children": [],
        },
    ]
    plist = {
        "WebBookmarkFileVersion": 1,
        "WebBookmarkType": "WebBookmarkTypeList",
        "Children": children,
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_BINARY)


def _write_plist(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def test_read_empty_plist(tmp_path: Path) -> None:
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist())
    result = read(p)
    assert result == {"bookmark_bar": [], "other": []}


def test_read_bookmarks(tmp_path: Path) -> None:
    bar_items = [
        {
            "WebBookmarkType": "WebBookmarkTypeLeaf",
            "WebBookmarkUUID": "UUID-1",
            "URLString": "https://example.com",
            "URIDictionary": {"title": "Example"},
        },
    ]
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist(bookmark_bar=bar_items))
    result = read(p)
    assert len(result["bookmark_bar"]) == 1
    bm = result["bookmark_bar"][0]
    assert isinstance(bm, Bookmark)
    assert bm.url == "https://example.com"
    assert bm.title == "Example"


def test_read_folders(tmp_path: Path) -> None:
    bar_items = [
        {
            "WebBookmarkType": "WebBookmarkTypeList",
            "WebBookmarkUUID": "FOLDER-UUID",
            "Title": "Dev",
            "Children": [
                {
                    "WebBookmarkType": "WebBookmarkTypeLeaf",
                    "WebBookmarkUUID": "UUID-2",
                    "URLString": "https://github.com",
                    "URIDictionary": {"title": "GitHub"},
                },
            ],
        },
    ]
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist(bookmark_bar=bar_items))
    result = read(p)
    assert len(result["bookmark_bar"]) == 1
    folder = result["bookmark_bar"][0]
    assert isinstance(folder, Folder)
    assert folder.title == "Dev"
    assert len(folder.children) == 1


def test_write_preserves_presets(tmp_path: Path) -> None:
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist())

    bm = Bookmark("New", "https://new.com")
    write({"bookmark_bar": [bm], "other": []}, p)

    with open(p, "rb") as f:
        plist = plistlib.load(f)

    titles = [c.get("Title", "") for c in plist["Children"]]
    identifiers = [c.get("WebBookmarkIdentifier", "") for c in plist["Children"]]
    assert "History" in titles
    assert "BookmarksBar" in titles
    assert "com.apple.ReadingList" in identifiers


def test_other_lives_at_root_and_replaces_user_items(tmp_path: Path) -> None:
    existing_user_item = {
        "WebBookmarkType": "WebBookmarkTypeList",
        "WebBookmarkUUID": "OLD-UUID",
        "Title": "OldFolder",
        "Children": [
            {
                "WebBookmarkType": "WebBookmarkTypeLeaf",
                "WebBookmarkUUID": "OLD-LEAF",
                "URLString": "https://old.example",
                "URIDictionary": {"title": "Old"},
            },
        ],
    }
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist(other=[existing_user_item]))

    # Read should surface the root-level user folder as `other`.
    parsed = read(p)
    assert any(isinstance(i, Folder) and i.title == "OldFolder" for i in parsed["other"])

    # Writing replaces user root items, leaves presets in place.
    new_other: list[BookmarkItem] = [
        Folder("Dev", [Bookmark("GH", "https://github.com")]),
        Bookmark("Loose", "https://loose.example"),
    ]
    write({"bookmark_bar": [], "other": new_other}, p)

    with open(p, "rb") as f:
        plist = plistlib.load(f)

    titles = [c.get("Title", "") for c in plist["Children"]]
    identifiers = [c.get("WebBookmarkIdentifier", "") for c in plist["Children"]]
    assert "OldFolder" not in titles
    assert "Dev" in titles
    assert "BookmarksBar" in titles
    assert "History" in titles
    assert "com.apple.ReadingList" in identifiers
    # And the parsed `other` reflects the new content.
    parsed = read(p)
    other_titles = {i.title for i in parsed["other"]}
    assert other_titles == {"Dev", "Loose"}


def test_read_skips_reading_list_by_identifier(tmp_path: Path) -> None:
    """The real Reading List entry is skipped by identifier even if title varies."""
    rl = {
        "WebBookmarkType": "WebBookmarkTypeList",
        "WebBookmarkIdentifier": "com.apple.ReadingList",
        "Title": "Reading List",  # display title, not the canonical preset title
        "Children": [
            {
                "WebBookmarkType": "WebBookmarkTypeLeaf",
                "URLString": "https://rl.example",
                "URIDictionary": {"title": "x"},
            },
        ],
    }
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist(other=[rl]))
    parsed = read(p)
    assert parsed["other"] == []


def test_read_skips_reading_list_by_title_without_identifier(tmp_path: Path) -> None:
    """A list titled 'com.apple.ReadingList' but lacking the identifier is also skipped."""
    bogus = {
        "WebBookmarkType": "WebBookmarkTypeList",
        "Title": "com.apple.ReadingList",
        "Children": [
            {
                "WebBookmarkType": "WebBookmarkTypeLeaf",
                "URLString": "https://oops.example",
                "URIDictionary": {"title": "oops"},
            },
        ],
    }
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist(other=[bogus]))
    parsed = read(p)
    assert parsed["other"] == []


def test_write_drops_preset_titled_folder_from_other(tmp_path: Path) -> None:
    """Merged 'other' containing a 'com.apple.ReadingList' folder must not be written."""
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist())

    write(
        {
            "bookmark_bar": [],
            "other": [
                Folder("com.apple.ReadingList", [Bookmark("x", "https://x.example")]),
                Folder("Real", [Bookmark("y", "https://y.example")]),
            ],
        },
        p,
    )

    with open(p, "rb") as f:
        plist = plistlib.load(f)

    # Real ReadingList preset (by identifier) is preserved exactly once.
    rl_entries = [
        c for c in plist["Children"]
        if c.get("WebBookmarkIdentifier") == "com.apple.ReadingList"
    ]
    assert len(rl_entries) == 1
    # The bogus user folder did not get serialized as a separate root entry.
    titled_rl = [
        c for c in plist["Children"]
        if c.get("Title") == "com.apple.ReadingList"
        and c.get("WebBookmarkIdentifier") != "com.apple.ReadingList"
    ]
    assert titled_rl == []
    # The non-bogus folder is present.
    assert any(c.get("Title") == "Real" for c in plist["Children"])


def test_read_skips_bookmarks_menu(tmp_path: Path) -> None:
    """A 'BookmarksMenu' container at root is not surfaced as user content."""
    menu = {
        "WebBookmarkType": "WebBookmarkTypeList",
        "Title": "BookmarksMenu",
        "WebBookmarkUUID": "MENU-UUID",
        "Children": [
            {
                "WebBookmarkType": "WebBookmarkTypeLeaf",
                "URLString": "https://menu.example",
                "URIDictionary": {"title": "Menu Item"},
            },
        ],
    }
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist(other=[menu]))
    parsed = read(p)
    assert parsed["other"] == []


def test_write_preserves_existing_bookmarks_menu_in_place(tmp_path: Path) -> None:
    """An existing BookmarksMenu container is left intact on write."""
    menu = {
        "WebBookmarkType": "WebBookmarkTypeList",
        "Title": "BookmarksMenu",
        "WebBookmarkUUID": "MENU-UUID",
        "Children": [
            {
                "WebBookmarkType": "WebBookmarkTypeLeaf",
                "WebBookmarkUUID": "MENU-LEAF",
                "URLString": "https://menu.example",
                "URIDictionary": {"title": "Menu Item"},
            },
        ],
    }
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist(other=[menu]))

    write(
        {
            "bookmark_bar": [],
            "other": [Folder("Real", [Bookmark("y", "https://y.example")])],
        },
        p,
    )

    with open(p, "rb") as f:
        plist = plistlib.load(f)

    menu_entries = [c for c in plist["Children"] if c.get("Title") == "BookmarksMenu"]
    assert len(menu_entries) == 1
    assert menu_entries[0].get("WebBookmarkUUID") == "MENU-UUID"
    # The original child was preserved (not a fresh replacement).
    leaves = menu_entries[0].get("Children", [])
    assert any(
        leaf.get("URLString") == "https://menu.example" for leaf in leaves
    )
    assert any(c.get("Title") == "Real" for c in plist["Children"])


def test_write_drops_bookmarks_menu_folder_from_other(tmp_path: Path) -> None:
    """If `other` contains a 'BookmarksMenu' folder, don't write it."""
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist())
    write(
        {
            "bookmark_bar": [],
            "other": [
                Folder("BookmarksMenu", [Bookmark("x", "https://x.example")]),
                Folder("Real", []),
            ],
        },
        p,
    )

    with open(p, "rb") as f:
        plist = plistlib.load(f)

    titles = [c.get("Title", "") for c in plist["Children"]]
    assert titles.count("BookmarksMenu") == 0
    assert "Real" in titles


def test_strip_preset_lookalikes_drops_only_top_level_preset_titles() -> None:
    items: list[BookmarkItem] = [
        Folder("com.apple.ReadingList", []),
        Folder("BookmarksMenu", []),
        Folder("Keep", [Folder("com.apple.ReadingList", [])]),  # nested, not stripped
        Bookmark("b", "https://b.example"),
    ]
    out = strip_preset_lookalikes(items)
    titles = [getattr(i, "title", None) for i in out]
    assert "com.apple.ReadingList" not in titles
    assert "BookmarksMenu" not in titles
    assert "Keep" in titles
    # Nested preset-titled folder is left alone — only top level is policed.
    keep = next(i for i in out if isinstance(i, Folder) and i.title == "Keep")
    assert isinstance(keep.children[0], Folder)
    assert keep.children[0].title == "com.apple.ReadingList"


def test_write_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "Bookmarks.plist"
    _write_plist(p, _make_plist())

    bm = Bookmark("Test", "https://test.com")
    folder = Folder("Dev", [Bookmark("GH", "https://github.com")])
    write({"bookmark_bar": [bm, folder], "other": []}, p)

    result = read(p)
    urls = {item.url for item in result["bookmark_bar"] if isinstance(item, Bookmark)}
    assert "https://test.com" in urls
    folders = [item for item in result["bookmark_bar"] if isinstance(item, Folder)]
    assert len(folders) == 1
    assert folders[0].title == "Dev"


# Property test: serialize then parse round-trips URLs.
titles_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=10,
)
bookmarks_st = st.builds(
    Bookmark,
    title=titles_st,
    url=st.from_regex(r"https://[a-z]{1,8}\.[a-z]{2,3}/[a-z0-9]{0,5}", fullmatch=True),
    date=st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 1, 1),
        timezones=st.just(timezone.utc),
    ),
)
items_st = st.lists(bookmarks_st, max_size=5)


@given(items=items_st)
@settings(max_examples=100)
def test_serialize_parse_roundtrip_urls(items: list[Bookmark]) -> None:
    serialized = _serialize_children(items)
    parsed = _parse_children(serialized)
    original_urls = {b.url for b in items}
    parsed_urls = {b.url for b in parsed if isinstance(b, Bookmark)}
    assert parsed_urls == original_urls
