"""logs.md merge for tools/land.py: both sides' new ``## YYYY-MM-DD`` entries, kept whole, in date order.

``rosy_harness.py lint`` rejects a log whose entry dates go backwards, and a line
union would fold lines entries share ("- 결정: 없음"). Standard library only.
"""

from __future__ import annotations

import re
from collections import Counter

DATE = re.compile(rb"^## (\d{4}-\d{2}-\d{2})")


def split(data: bytes) -> tuple[bytes, list[bytes]]:
    """(text before the first ``## `` line, each ``## `` block with the lines up to the next one)."""
    head: list[bytes] = []
    blocks: list[list[bytes]] = []
    for line in data.splitlines(keepends=True):
        if line.startswith(b"## "):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
        else:
            head.append(line)
    return b"".join(head), [b"".join(block) for block in blocks]


def shared(ours: bytes, theirs: bytes) -> bytes:
    """theirs' head and the entries both sides hold unchanged, in theirs' order: the base of this append-only log
    when git's is virtual (criss-cross history). A real merge base fails too: each holds one side's hand-merged
    entries, so both sides look like they inserted them."""
    head, blocks = split(theirs)
    mine = {_key(block) for block in split(ours)[1]}
    return head + b"".join(block for block in blocks if _key(block) in mine)


def _key(block: bytes) -> bytes:
    return block.rstrip()  # the blank line before the next entry is not part of the entry


def _date(block: bytes) -> bytes | None:
    match = DATE.match(block)
    return match.group(1) if match else None


def _new(base: list[bytes], side: list[bytes], may_reorder: bool = False) -> tuple[list[bytes], bool] | None:
    """(side's entries the base lacks, whether side kept base's blocks as a prefix), or None
    when side dropped, rewrote or reordered a base entry (moving its own new entries is not editing).
    ``may_reorder``: a side whose base entries are all there, only in another order, gives its new
    entries with prefix False; its order is then never kept."""
    pending = Counter(map(_key, base))
    if pending - Counter(map(_key, side)):
        return None
    if [k for k in map(_key, side) if k in pending] != list(map(_key, base)):
        if not may_reorder:
            return None
        return [x for x in side if _key(x) not in pending], False
    added = []
    for block in side:
        if pending[_key(block)]:
            pending[_key(block)] -= 1
        else:
            added.append(block)
    prefix = [_key(b) for b in side[:len(base)]] == [_key(b) for b in base]
    return added, prefix


def _anchored(theirs: list[bytes], ours: list[bytes], main_keys: set[bytes]) -> list[bytes] | None:
    """Main's entries in main's order; each entry only ours has goes after the entry it followed in ours, after
    main's own new entries at that spot. None when that puts a date before an earlier one."""
    kept = list(theirs)
    keys = [_key(x) for x in kept]
    main_only = main_keys - {_key(x) for x in ours}
    prev = -1  # index in kept of the entry our next new one follows; -1: right after the head
    for block in ours:
        k = _key(block)
        if k in keys:
            prev = keys.index(k)
            continue
        pos = prev + 1
        while pos < len(kept) and keys[pos] in main_only:
            pos += 1  # main's own new entry at the same spot stays first (main landed first)
        kept.insert(pos, block)
        keys.insert(pos, k)
        prev = pos
    days = [d for d in map(_date, kept) if d]
    return kept if days == sorted(days) else None


def append_blocks(base: bytes, ours: bytes, theirs: bytes) -> bytes | None:
    """The merged log, or None when a side changed an existing line (a human resolves it).

    Each side may add entries anywhere and move its own; it may not edit or drop a
    base entry or the text above the first entry. The result keeps one side's
    sequence (the side that inserted or moved entries, else theirs = main, which
    landed first) and inserts the other side's new entries after every entry dated
    on or before them, never above the last base entry: dates stay non-decreasing
    and same-date entries keep their side's order. When both sides inserted mid-file,
    main's sequence is kept and each of ours goes after the entry it followed, unless
    that would break date order.
    """
    (head, b), (oh, o), (th, t) = split(base), split(ours), split(theirs)
    if oh.rstrip() != head.rstrip() or th.rstrip() != head.rstrip():
        return None
    # this branch's own copy may hold main's entries in another order: a hand-fitted merge of main whose
    # order later main no longer matches (2026-10-26). Main's order wins; main reordering still refuses.
    mine, other = _new(b, o, may_reorder=True), _new(b, t)
    if mine is None or other is None:
        return None
    reordered = [k for k in map(_key, o) if k in {_key(x) for x in b}] != list(map(_key, b))
    if mine == ([], True) or (reordered and not mine[0]):
        return theirs
    if other == ([], True) and not reordered:
        return ours
    if not reordered and not mine[1] and not other[1]:
        # both sides inserted mid-file (2026-10-28 stop): main's sequence, each of ours after the entry it followed
        kept = _anchored(t, o, {_key(x) for x in t})
        if kept is None:
            return None
        top = th
    else:
        keep, extra, top = (o, other[0], oh) if not mine[1] and not reordered else (t, mine[0], th)
        old = {_key(x) for x in b}
        kept = list(keep)
        floor = max((i + 1 for i, x in enumerate(kept) if _key(x) in old), default=0)
        for block in extra:
            if _key(block) in {_key(x) for x in kept}:
                continue  # the same entry on both sides (a cherry-pick): keep one
            pos, day = len(kept), _date(block)
            while day and pos > floor and (_date(kept[pos - 1]) or b"") > day:
                pos -= 1
            kept.insert(pos, block)
    eol = b"\r\n" if b"\r\n" in ours + theirs else b"\n"
    body = [x if x.endswith(eol + eol) else x.rstrip(b"\r\n") + eol + eol for x in kept[:-1]]
    return top + b"".join(body) + kept[-1].rstrip(b"\r\n") + eol
