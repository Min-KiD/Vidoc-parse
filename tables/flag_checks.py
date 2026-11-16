"""Checks that need no answer key, as workflow flags. Every flag has `table`, `row`, `col` (None where the check
points at no cell) and `kind`:

  amount_not_in_table  box OCR reads an amount on a line of its own and no cell of the page holds it: a row, a column
                       or a table the reader left out. Fields amount (digits), y (top of the OCR line), text (the
                       line); table = the last table whose top is above the line, None when no table is.
  amount_unread        a cell amount that box OCR reads nowhere on the page: one of the two readers misread it.
                       Field mineru (the cell). Not raised on a page without box OCR.
  no_label_column      most rows with an amount have no cell with a word: the reader left the labels out.
  form_sum_fail        a line-code sum of form B01, B02 or B03 does not hold; on the total line. Fields form, code,
                       printed, parts_sum.
  statements_disagree  an equality between two statements (forms.between) does not hold; on the cash-flow line.
                       Field check.
  coded_row_empty      a line of a statement with a line code and no value at all (printed dashes dropped). Fields
                       form, code.
  malformed            see flag_malformed.

page_flags runs on one page, document_flags on all pages of a document (a statement spans pages).
"""
import re

from tables import coverage as K, forms as F
from tables.grid import ctype, nws, parse_amount, roles, value


def flag_malformed(s):
    """A value cell that looks like a number, does not parse as an amount and shows a misread separator: two or more
    marks ('3.882.700.00', two amounts in one cell) or more than three digits after a mark ('143.000000'). A single
    mark with fewer digits after it ('1.', '59,00', '27.1') is an item number, a decimal or a rate, not a fault."""
    s = nws(s)
    if not s or ctype(s) != "amount" or parse_amount(s) is not None:
        return False
    return len(re.findall(r"[.,]", s)) >= 2 or bool(re.search(r"[.,]\d{4,}", s))


def digit_vote(cell, ocr_extra, gemini):
    """cell: a MinerU amount box OCR reads nowhere; ocr_extra: amounts box OCR reads on lines of their own and no cell
    holds; gemini: amounts Gemini's tables of the page hold (Counters of digits, as coverage.amounts). Two readers
    against one: the cell rewritten with the other digits (same marks, same brackets) when exactly one amount of
    ocr_extra has as many digits and differs in 1 or 2 of them, and Gemini holds that amount and not the cell's.
    Else None."""
    d = re.sub(r"\D", "", cell)
    near = [a for a in ocr_extra if len(a) == len(d) and 0 < sum(x != y for x, y in zip(a, d)) <= 2]
    if len(near) != 1 or not gemini[near[0]] or gemini[d]:
        return None
    other = iter(near[0])
    return "".join(next(other) if ch.isdigit() else ch for ch in cell)


def header_rows(tb):
    rows = [[nws(value(c)) for c in row] for row in tb["rows"]]
    return tb["header_rows"] if "header_rows" in tb else roles(rows)["header_rows"] if rows else []


def bare(tb):
    """(rows with an amount and no word, rows with an amount) when the first are more than half, else None."""
    head = header_rows(tb)
    body = [[nws(value(c)) for c in row] for r, row in enumerate(tb["rows"]) if r not in head]
    am = [row for row in body if any(parse_amount(x) is not None and sum(ch.isdigit() for ch in x) >= 4 for x in row)]
    no_word = [row for row in am if not any(sum(ch.isalpha() for ch in x) >= 3 for x in row)]
    return (len(no_word), len(am)) if 2 * len(no_word) > len(am) else None


def page_flags(tables, ocr_lines):
    flags = []
    for t, tb in enumerate(tables):
        b = bare(tb)
        if b:
            flags.append({"table": t, "row": None, "col": None, "kind": "no_label_column",
                          "rows_without_word": b[0], "rows_with_amount": b[1]})
    if not ocr_lines:
        return flags
    boxes = [tb["bbox"] for tb in tables if tb.get("bbox")]
    tops = [(tb["bbox"][1], t) for t, tb in enumerate(tables) if tb.get("bbox")]
    inside = lambda l: any(b[1] <= l["y0"] and l["y1"] <= b[3] for b in boxes)
    extra = K.alarms(ocr_lines, tables)[0]
    for a, n in sorted(extra.items()):
        # an amount read on more lines than the cells hold: the lines outside every table box are the unheld ones
        here = [l for l in ocr_lines if a in K.amounts(l["text"]) and not K.in_sentence(l["text"])]
        for l in sorted(here, key=lambda l: (inside(l), l["y0"]))[:n]:
            above = [(top, t) for top, t in tops if top <= l["y0"]]
            flags.append({"table": max(above)[1] if above else None, "row": None, "col": None,
                          "kind": "amount_not_in_table", "amount": a, "y": round(l["y0"]), "text": l["text"]})
    for a in K.unread(ocr_lines, tables):
        for t, tb in enumerate(tables):
            for r, row in enumerate(tb["rows"]):
                for c, x in enumerate(row):
                    if a in K.amounts(value(x)):
                        flags.append({"table": t, "row": r, "col": c, "kind": "amount_unread", "mineru": value(x)})
    return flags


def statement_tables(pages):
    """{(page, table)} that forms.read takes for a statement."""
    return {(p, t) for p, t, _, _ in F.read(pages)[4].values()}


def document_flags(pages):
    """pages: {page: tables}. Returns {page: [flags]}."""
    V, _, empty, _, place = F.read(pages)
    out = {}
    for p, st, code, t, r in empty:
        out.setdefault(p, []).append({"table": t, "row": r, "col": None, "kind": "coded_row_empty", "form": st,
                                      "code": code})
    for st, total, j, printed, got in F.sums(V)[1]:
        p, t, r, cols = place[st, total]
        out.setdefault(p, []).append({"table": t, "row": r, "col": cols[j], "kind": "form_sum_fail", "form": st,
                                      "code": total, "printed": printed, "parts_sum": got})
    for check, holds in F.between(V).items():
        if not holds:  # the name tells the cash-flow line: 'B03 70 = ...'
            p, t, r, _ = place["B03", re.search(r"B03 (\d+)", check).group(1)]
            out.setdefault(p, []).append({"table": t, "row": r, "col": None, "kind": "statements_disagree",
                                          "check": check})
    return out
