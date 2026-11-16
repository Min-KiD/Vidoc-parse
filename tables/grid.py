"""Cells, grids and tables: reading MinerU's HTML/markdown into grids, normalising and typing cells, column roles,
and the row and column joins every reader pair uses.

A grid is a list of rows, a row a list of cell strings, every row equally long. A table is
{"rows": grid, "title": str, "bbox": [x0, y0, x1, y1] in pixels of the upright page image, or None}.
"""
import difflib, html as _html, re, unicodedata
from html.parser import HTMLParser

DASHES = {"-", "–", "—", "−"}
CODE_RE = re.compile(r"^\d{1,3}[a-z]?$")
NOTE_RE = re.compile(r"^\d{1,2}(\.\d{1,2})*[a-z]?$")
UNIT_RE = re.compile(r"(?i)đơn vị tính\s*:?\s*([^<\n|]+)")
_GROUPED = re.compile(r"^\d{1,3}(?:([., ])\d{3})(?:\1\d{3})*$")
_PLAIN = re.compile(r"^\d+$")
PCT_RE = re.compile(r"^\(?[+-]?\d[\d.,]*\)?\s*%$")
INT_RE = re.compile(r"^\d{1,4}[a-zA-Z]?$|^\d{1,2}(\.\d{1,2})+[a-zA-Z]?$")


# ---------- amounts and cells ----------

def parse_amount(raw: str | None) -> int | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if s in DASHES:
        return 0
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    if s[:1] in DASHES and len(s) > 1:
        neg, s = True, s[1:].strip()
    if _PLAIN.match(s) or _GROUPED.match(s):
        v = int(re.sub(r"[., ]", "", s))
        return -v if neg else v
    return None


def nws(s):
    """NFC + whitespace normalisation. Paddle writes line breaks as a literal backslash-n; treated as whitespace."""
    s = (s or "").replace("\\n", " ")
    return " ".join(unicodedata.normalize("NFC", s).split())


def nodiac(s):
    s = unicodedata.normalize("NFD", nws(s).replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def two_amounts(s):
    """True when a cell holds two or more money amounts (glued, or split by space/newline)."""
    s = nws(s)
    if not s or re.search(r"[^\W\d_]", s):
        return False
    parts = re.findall(r"\(?\d{1,3}(?:[.,]\d{3})+\)?", s)
    return len(parts) >= 2


def ctype(s, role="value"):
    """amount | dash | blank | pct | int | text. role: 'value' for money columns, anything else otherwise."""
    s = nws(s)
    if not s:
        return "blank"
    if s in DASHES:
        return "dash"
    if PCT_RE.match(s):
        return "pct"
    if role != "value" and INT_RE.match(s):
        return "int"
    if parse_amount(s) is not None:
        return "amount"
    if two_amounts(s) or (re.search(r"\d", s) and not re.search(r"[^\W\d_]", s) and re.fullmatch(r"[\d.,()\s+-]+", s)):
        return "amount"  # malformed number or two values in one cell
    return "text"


def value(c):
    """Text of a cell: a string in reader and workflow output, a dict in a gold."""
    return c["value"] if isinstance(c, dict) else c


def amount_key(cells):
    return tuple(v for v in (parse_amount(nws(c)) for c in cells) if v)


# ---------- MinerU output to grids ----------

class _TableParser(HTMLParser):
    """Collects every <table> as a list of rows of (text, rowspan, colspan); nested tables are flattened."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._rows, self._row, self._cell, self._depth = [], None, None, None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in ("td", "th") and self._depth and self._row is not None:
            def span(k):
                try:
                    return max(1, int(a.get(k) or 1))
                except ValueError:
                    return 1
            self._cell = [[], span("rowspan"), span("colspan")]
        elif tag == "br" and self._cell is not None:
            self._cell[0].append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append((" ".join("".join(self._cell[0]).split()), self._cell[1], self._cell[2]))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                self.tables.append(self._rows)
                self._rows = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell[0].append(data)


def expand(rows):
    """rows of (text, rowspan, colspan) -> rectangular grid. Unlike html_grid.expand, a spanned cell's text is kept
    only in its top-left grid cell; the covered cells are "" (Paddle and Gemini write spans that way)."""
    grid, pending = [], set()
    for r, row in enumerate(rows):
        out, c, cells = [], 0, list(row)
        while cells or (r, c) in pending:
            if (r, c) in pending:
                pending.discard((r, c)); out.append(""); c += 1; continue
            text, rs, cs = cells.pop(0)
            for k in range(cs):
                out.append(text if k == 0 else "")
                for d in range(1, rs):
                    pending.add((r + d, c + k))
            c += cs
        grid.append(out)
    width = max((len(g) for g in grid), default=0)
    return [g + [""] * (width - len(g)) for g in grid]


def expand_repeat(rows):
    """rows of (text, rowspan, colspan) -> rectangular grid of strings."""
    grid, pending = [], {}  # pending[(r, c)] = text carried by a rowspan
    for r, row in enumerate(rows):
        out, c = [], 0
        cells = list(row)
        while cells or (r, c) in pending:
            if (r, c) in pending:
                out.append(pending.pop((r, c))); c += 1; continue
            text, rs, cs = cells.pop(0)
            for k in range(cs):
                out.append(text)
                for d in range(1, rs):
                    pending[(r + d, c + k)] = text
            c += cs
        grid.append(out)
    # rowspans running past the last <tr>
    extra = sorted({r for r, _ in pending})
    for r in extra:
        width = max(c for rr, c in pending if rr == r) + 1
        grid.append([pending.get((r, c), "") for c in range(width)])
    width = max((len(g) for g in grid), default=0)
    return [g + [""] * (width - len(g)) for g in grid]


def _md_tables(text):
    """Markdown pipe tables -> (start offset, grid). A cell's own '|' is written '\\|' and does not end the cell."""
    out, block, start, pos = [], [], None, 0
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s.startswith("|"):
            if start is None:
                start = pos
            if not re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", s):
                cells = re.split(r"(?<!\\)\|", s)[1:]
                if cells and cells[-1] == "":  # the closing pipe
                    cells.pop()
                block.append([c.replace("\\|", "|").strip() for c in cells])
        elif block:
            out.append((start, block)); block, start = [], None
        pos += len(line)
    if block:
        out.append((start, block))
    return [(s, expand_repeat([[(c, 1, 1) for c in row] for row in b])) for s, b in out]


def _context(text, start):
    before = re.sub(r"<[^>]+>", " ", text[:start])
    lines = [l.strip(" #*") for l in before.splitlines() if l.strip(" #*|")]
    title = lines[-1] if lines else ""
    m = list(UNIT_RE.finditer(before[-400:]))
    return title, (m[-1].group(1).strip() if m else None)


def md_grids(text):
    found = []
    for m in re.finditer(r"(?is)<table\b.*?</table>", text):
        P = _TableParser(); P.feed(m.group(0)); P.close()
        for rows in P.tables:
            found.append((m.start(), expand(rows)))
    stripped = re.sub(r"(?is)<table\b.*?</table>", lambda m: " " * len(m.group(0)), text)
    found += _md_tables(stripped)
    out = []
    for start, grid in sorted(found, key=lambda x: x[0]):
        title, _ = _context(text, start)
        out.append({"rows": [[_html.unescape(c) for c in row] for row in grid], "title": title})
    return out


def trim(tables):
    """Drop columns that are empty in every row (MinerU markdown pads p67 with 6 empty columns)."""
    for t in tables:
        keep = [c for c in range(len(t["rows"][0])) if any(nws(r[c]) for r in t["rows"])]
        t["rows"] = [[r[c] for c in keep] for r in t["rows"]]
    return [t for t in tables if t["rows"] and t["rows"][0]]


# ---------- column roles ----------

def _is_amount(s):
    return parse_amount(s) is not None and not CODE_RE.match(s.strip())


def _frac(cells, rx):
    cells = [c.strip() for c in cells if c.strip()]
    return (sum(bool(rx.match(c)) for c in cells) / len(cells), len(cells)) if cells else (0.0, 0)


def roles(rows):
    """header rows, label/code/note columns and value columns of a grid (generalises html_grid.grid_to_table
    to text tables: no amount row -> header = rows before the first row holding a digit, if that is < half)."""
    width = len(rows[0]) if rows else 0
    isamt = lambda s: _is_amount(nws(s)) and nws(s) not in DASHES
    first = next((r for r, row in enumerate(rows) if any(isamt(x) for x in row[1:])), None)
    numeric = first is not None
    if not numeric:
        d = next((r for r, row in enumerate(rows) if any(re.search(r"\d", x) for x in row)), len(rows))
        first = d if d < len(rows) / 2 else 0
    head, body = rows[:first], rows[first:]
    hdr = [" ".join(dict.fromkeys(nws(h[c]) for h in head if nws(h[c]))) for c in range(width)]
    col = lambda c: [nws(row[c]) for row in body]
    letters = [sum(bool(re.search(r"[^\W\d_]", x)) for x in col(c)) for c in range(width)]
    label = max(range(width), key=lambda c: (letters[c], -c)) if width else 0
    if not numeric:
        label = next((c for c in range(width) if letters[c] >= max(1, len(body) // 2)), label)
    code = note = None
    for c in range(width):
        if c == label or c > label + 2:
            continue
        f, n = _frac(col(c), CODE_RE)
        if (re.search(r"(?i)\bmã\b", hdr[c]) or f >= 0.7) and n >= 2 and not re.search(r"(?i)thuyết", hdr[c]) \
                and not any("." in x for x in col(c)) and code is None:
            code = c
    for c in range(width):
        if c in (label, code) or c > label + 3:
            continue
        f, n = _frac(col(c), NOTE_RE)
        if re.search(r"(?i)thuyết\s*minh", hdr[c]) or (f >= 0.9 and n >= 1 and not any(
                _is_amount(x) and not NOTE_RE.match(x) for x in col(c))):
            note = c; break
    value = [c for c in range(width) if c > label and c not in (code, note)] if numeric else []
    role = {}
    for c in range(width):
        role[c] = ("label" if c == label else "code" if c == code else "note" if c == note
                   else "value" if c in value and any(ctype(x) in ("amount", "dash") for x in col(c)) else "text")
    return {"header_rows": list(range(first)), "numeric": numeric, "label": label, "code": code, "note": note,
            "role": [role[c] for c in range(width)], "headers": hdr}


# ---------- joins ----------

def join_rows(km, kg):
    """km, kg: per-row tuples of non-zero amounts (page order). Returns {mineru_row: (gemini_row, 'amounts'|'position')}."""
    im = [i for i, k in enumerate(km) if k]          # MinerU rows with amounts
    ig = [j for j, k in enumerate(kg) if k]
    pairs = []
    sm = difflib.SequenceMatcher(a=[km[i] for i in im], b=[kg[j] for j in ig], autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for x in range(n):
            pairs.append((im[a + x], ig[b + x]))
    out = {i: (j, "amounts") for i, j in pairs}
    for (i0, j0), (i1, j1) in zip([(-1, -1)] + pairs, pairs + [(len(km), len(kg))]):
        sm_ = [i for i in range(i0 + 1, i1) if not km[i]]
        sg_ = [j for j in range(j0 + 1, j1) if not kg[j]]
        if sm_ and len(sm_) == len(sg_):
            for i, j in zip(sm_, sg_):
                out[i] = (j, "position")
    return out


def column_map(Arows, Brows, pairs):
    """A col -> B col, one-to-one, greedy by equal-cell votes over matched rows (readers order label/code
    differently, so the map need not be monotonic); an unvoted column next to a mapped one takes the
    adjacent free B column."""
    wa, wb = max(map(len, Arows)), max(map(len, Brows))
    V = [[0] * wb for _ in range(wa)]
    for i, j in pairs:
        a, b = Arows[i], Brows[j]
        for c, x in enumerate(a):
            x = nws(x)
            if not x or x in DASHES:
                continue
            xv = parse_amount(x)
            for k, y in enumerate(b):
                y = nws(y)
                if y == x or (xv and parse_amount(y) == xv) or (ctype(x) == "text" and nodiac(x).lower() == nodiac(y).lower()):
                    V[c][k] += 1
    out, used = {}, set()
    for n, c, k in sorted(((V[c][k], c, k) for c in range(wa) for k in range(wb) if V[c][k]),
                          key=lambda x: (-x[0], abs(x[1] - x[2]))):
        if c not in out and k not in used:
            out[c] = k; used.add(k)
    for _ in range(2):
        for c in range(wa):
            if c in out:
                continue
            for d in (-1, 1):
                k = out.get(c - d)
                if k is not None and 0 <= k + d < wb and k + d not in used:
                    out[c] = k + d; used.add(k + d); break
    if not out and wa == wb:
        out = {c: c for c in range(wa)}
    return out
