"""Coverage: an amount that box OCR reads on a page and that no table cell holds (FINDINGS E11). It is the one check
that sees a row, a column or a table the reader left out. No answer key, no model but the box OCR.

An amount in a sentence is kept apart from an amount on a line of its own: a report also writes amounts in its
running text, and those belong to no table (FINDINGS E12).
"""
import re
from collections import Counter

from tables.grid import value

AMOUNT = re.compile(r"\(?\d{1,3}(?:[.,]\d{3})+\)?")


def amounts(text):
    """Digits of every amount written in groups of three ('83.455.099' -> '83455099'). Box OCR sometimes reads a
    space next to a separator."""
    s = re.sub(r"(?<=[.,])\s+(?=\d)|(?<=\d)\s+(?=[.,])", "", str(text or ""))
    return [re.sub(r"\D", "", m.group(0)) for m in AMOUNT.finditer(s)]


def held(tabs):
    return Counter(a for t in tabs for row in t["rows"] for c in row for a in amounts(value(c)))


def uncovered(seen, cells):
    """seen: amounts box OCR reads on a page, cells: amounts the tables of the page hold (Counters).
    Returns (the amounts of `seen` that no cell holds, their number before the tail rule). Tail rule: an OCR amount
    that is the tail of a cell amount box OCR did not read is that cell read short ('183.300' for '15.183.300')."""
    extra, unread = seen - cells, cells - seen
    raw = sum(extra.values())
    for a in list(extra):
        for k in list(unread):
            n = min(extra[a], unread[k]) if k != a and k.endswith(a) else 0
            extra[a] -= n
            unread[k] -= n
    return +extra, raw


def in_sentence(text):
    """Running text and not a table row: the OCR line has 12 letters or more besides its amounts. Of 3778 amounts
    that the tables of three documents hold, box OCR reads 8 in such a line (FINDINGS E12)."""
    return sum(ch.isalpha() for ch in AMOUNT.sub("", text)) >= 12


def alarms(lines, tabs):
    """lines: box OCR lines of a page, tabs: its tables. Returns (amounts on lines of their own that no cell holds,
    amounts in sentences that no cell holds, amounts read). Cells are matched to the lines of their own first."""
    cells = held(tabs)
    rows = Counter(a for l in lines if not in_sentence(l["text"]) for a in amounts(l["text"]))
    text = Counter(a for l in lines if in_sentence(l["text"]) for a in amounts(l["text"]))
    return uncovered(rows, cells)[0], text - (cells - rows), sum(rows.values()) + sum(text.values())


def unread(lines, tabs):
    """Amounts of the cells that box OCR reads nowhere on the page, not even inside a longer run of digits (box OCR
    reads some separators as a space or as nothing). The two readers differ on such an amount: one misread it."""
    digits = [re.sub(r"\D", "", l["text"]) for l in lines]
    return sorted(a for a in held(tabs) if not any(a in d for d in digits))
