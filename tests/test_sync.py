# SPDX-License-Identifier: MIT
"""Property tests for the bookmark merge algorithm."""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from host.main import tree_from_dicts, tree_to_dicts
from host.sync import (
    Bookmark,
    BookmarkItem,
    Folder,
    bookmarkitem_from_dict,
    bookmarkitem_to_dict,
    merge_trees,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

urls = st.from_regex(r"https://[a-z]{1,10}\.[a-z]{2,4}/[a-z0-9]{0,8}", fullmatch=True)
titles = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=1,
    max_size=20,
)
dates = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 1, 1),
    timezones=st.just(timezone.utc),
)

bookmarks = st.builds(Bookmark, title=titles, url=urls, date=dates)

# Folders up to 2 levels deep to keep tests fast.
leaf_children = st.lists(bookmarks, max_size=5)
folders_depth1 = st.builds(
    Folder, title=titles, children=leaf_children,
)
tree_items = st.lists(
    st.one_of(bookmarks, folders_depth1),
    max_size=6,
)


def _all_urls(items: list[BookmarkItem]) -> set[str]:
    result: set[str] = set()
    for item in items:
        if isinstance(item, Bookmark):
            result.add(item.url)
        elif isinstance(item, Folder):
            result |= _all_urls(item.children)
    return result


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(a=tree_items)
@settings(max_examples=200)
def test_idempotent(a: list[BookmarkItem]) -> None:
    """merge(A, A) produces the same URLs as A."""
    merged, deleted = merge_trees(a, a)
    assert deleted == []
    assert _all_urls(merged) == _all_urls(a)


@given(a=tree_items, b=tree_items)
@settings(max_examples=200)
def test_commutative(a: list[BookmarkItem], b: list[BookmarkItem]) -> None:
    """merge(A, B) and merge(B, A) contain the same URLs."""
    m1, _ = merge_trees(a, b)
    m2, _ = merge_trees(b, a)
    assert _all_urls(m1) == _all_urls(m2)


@given(a=tree_items, b=tree_items)
@settings(max_examples=200)
def test_superset(a: list[BookmarkItem], b: list[BookmarkItem]) -> None:
    """merge(A, B) contains all URLs from A and B (without previous state)."""
    merged, _ = merge_trees(a, b)
    assert _all_urls(merged) >= _all_urls(a)
    assert _all_urls(merged) >= _all_urls(b)


@given(a=tree_items, b=tree_items)
@settings(max_examples=200)
def test_no_data_loss(a: list[BookmarkItem], b: list[BookmarkItem]) -> None:
    """Without previous state, no bookmarks are deleted."""
    _, deleted = merge_trees(a, b)
    assert deleted == []


# ---------------------------------------------------------------------------
# Deletion detection tests
# ---------------------------------------------------------------------------


def test_deletion_detected_when_removed_from_one_side() -> None:
    bm = Bookmark("Example", "https://example.com")
    previous: list[BookmarkItem] = [bm]
    chrome: list[BookmarkItem] = [bm]
    safari: list[BookmarkItem] = []  # removed from Safari

    merged, deleted = merge_trees(chrome, safari, previous)
    assert len(deleted) == 1
    assert deleted[0].url == "https://example.com"
    assert _all_urls(merged) == set()


def test_deletion_detected_when_removed_from_chrome() -> None:
    bm = Bookmark("Example", "https://example.com")
    previous: list[BookmarkItem] = [bm]
    chrome: list[BookmarkItem] = []  # removed from Chrome
    safari: list[BookmarkItem] = [bm]

    merged, deleted = merge_trees(chrome, safari, previous)
    assert len(deleted) == 1
    assert deleted[0].url == "https://example.com"
    assert _all_urls(merged) == set()


def test_new_bookmark_not_deleted_without_previous() -> None:
    bm = Bookmark("Example", "https://example.com")
    chrome: list[BookmarkItem] = [bm]
    safari: list[BookmarkItem] = []

    merged, deleted = merge_trees(chrome, safari)
    assert deleted == []
    assert _all_urls(merged) == {"https://example.com"}


def test_conflict_keeps_later_date() -> None:
    early = datetime(2024, 1, 1, tzinfo=timezone.utc)
    late = datetime(2025, 6, 1, tzinfo=timezone.utc)
    bm_old = Bookmark("Old Title", "https://example.com", date=early)
    bm_new = Bookmark("New Title", "https://example.com", date=late)

    merged, _ = merge_trees([bm_old], [bm_new])
    assert len(merged) == 1
    assert isinstance(merged[0], Bookmark)
    assert merged[0].title == "New Title"


def test_folder_merge() -> None:
    bm1 = Bookmark("A", "https://a.com")
    bm2 = Bookmark("B", "https://b.com")
    chrome: list[BookmarkItem] = [Folder("Dev", [bm1])]
    safari: list[BookmarkItem] = [Folder("Dev", [bm2])]

    merged, _ = merge_trees(chrome, safari)
    assert len(merged) == 1
    assert isinstance(merged[0], Folder)
    assert _all_urls(merged[0].children) == {"https://a.com", "https://b.com"}


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


@given(items=tree_items)
@settings(max_examples=100)
def test_serialization_roundtrip(items: list[BookmarkItem]) -> None:
    dicts = tree_to_dicts(items)
    recovered = tree_from_dicts(dicts)
    assert _all_urls(recovered) == _all_urls(items)


def test_from_dict_to_dict_identity() -> None:
    bm = Bookmark("X", "https://x.com", date=datetime(2025, 3, 1, tzinfo=timezone.utc))
    d = bookmarkitem_to_dict(bm)
    assert bookmarkitem_from_dict(d) == bm

    f = Folder("F", [bm])
    d = bookmarkitem_to_dict(f)
    recovered = bookmarkitem_from_dict(d)
    assert isinstance(recovered, Folder)
    assert recovered.title == "F"
    assert len(recovered.children) == 1
