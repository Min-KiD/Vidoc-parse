"""Stage 5: the final tables of a document, from the three reads -> <doc>/tables/pNN.json.

usage: python -m tables.workflow <doc>

Numbers, dashes and columns come from MinerU; the spelling of text cells from Gemini, on the rows joined by their
amounts (grid.join_rows). MinerU's read of a page is its first read with the second reads that
reread.py accepted (reread.json in MinerU's folder) in place of the tables they read again (with_rereads;
change table_reread); everything below works on that read. What changed:

  rule 1  A MinerU cell that holds exactly two amounts, above an empty cell, is two printed lines read into one
          cell: the second amount moves down. Done before the rows are joined, so both rows join by their own amount.
  rule 2  Gemini's text replaces MinerU's only where both cells show the same print (SAME): Gemini corrects
          spelling, spacing and diacritics, it is not a source of content. It does not fill a cell MinerU left
          empty (it repeats a name the page prints once for several rows, and it names unlabelled subtotal rows),
          does not empty a cell MinerU filled (its header row has no label, code or note header) and does not
          reword one (it prefixes 'Trong đó:' to the rows under that heading). Applied to label and text columns
          and to every cell of a header row (workflow_v1 left the headers of value columns as MinerU read them).
          Gemini's text is first cut to the cell's own part (own_part): an item number MinerU reads in the cell
          to the left ('A.', 'ii)') and Gemini reads at the start of this cell is not written twice.
  rule 3  A MinerU amount written in groups of three digits with both '.' and ',' ('4,835.204') gets the table's
          thousands separator, the one its other amounts show. Only a mark before the last group break is changed:
          it cannot be a decimal mark. Done before the rows are joined, like rule 1.
  step 3  MinerU rows are regrouped the way Gemini groups them, wherever MinerU's own text confirms it.
          Between two rows joined by amounts, a Gemini row may take a run of MinerU rows that hold text only and have
          no Gemini row yet. The run is accepted when, read as one row, it shows the Gemini row's text in every
          column (SAME) and every row of the run is needed for that. The joined rows above and below may take the
          runs next to them (a label that wraps onto lines of its own). A MinerU label equal to the labels of its
          Gemini row and of the next, otherwise empty, Gemini row is cut in two. Text is only moved: nothing is
          copied from Gemini here, so a Gemini row that MinerU did not read is flagged (gemini_only_row), not added.
          A line that ends with ':' is a heading for the rows under it and is never read as part of the next row.
          Not handled: a row whose text wraps both above and below its amount line (neither side fits alone).
  step 3b A MinerU row with no amount that is still not joined takes the next free Gemini row with no amount, in
          page order, that shows the same print: letters and digits of the whole row, cells in any order, at SAME
          (text_join; join kind `text`, text_source `gemini (text join)`). Rule 2 then runs on it as on any joined
          row. A table pair with no row joined by amounts takes its column map from its text-joined rows.
  step 4  A Gemini row that MinerU did not read is added when the rows above it prove it: each of its
          amounts is the sum of the amounts directly above it in its column (MinerU leaves out the total printed
          under the last row of a page). Only the amounts are taken; see total_row. Any other such row stays flagged.
  rule 4  A MinerU amount that box OCR reads nowhere on the page is rewritten with the digits of the one amount box
          OCR reads on a line of its own, in no cell, with as many digits and 1 or 2 of them different, when Gemini
          holds that amount and not MinerU's (flag_checks.digit_vote: two readers against one). text_source 'ocr+gemini',
          change digit_fixed. Done after step 3, before any flag.

Flags: row_not_joined (a MinerU row no Gemini row was joined to), amount_mismatch and text_diff (MinerU and
Gemini differ in a joined cell), gemini_only_row (step 3): a Gemini row with text at a place where MinerU has no
row at all, put on the MinerU row above it. malformed is raised by flag_checks.flag_malformed, on value cells only.
identity_fail (sums found by identities.py) passes when off by at most 1 per term and is not raised on a statement
table: forms.py checks those by their line codes (form_sum_fail). The checks of flag_checks.py add
amount_not_in_table, amount_unread, no_label_column (per page), form_sum_fail, statements_disagree and
coded_row_empty (per document). text_diff compares letters and digits only (`key`), in every column of
a header row too; a difference in marks, spacing, punctuation or a unit line is not flagged. A cell Gemini fills
and MinerU left empty is flagged only when the text is not a repeat of a MinerU cell further up in the column.
blank_or_dash: a value cell of a joined body row that MinerU leaves empty where Gemini has a dash (value_flags). The
cell is not changed: Gemini is no source for dashes. The other way (MinerU dash, Gemini empty) is not flagged: MinerU
was right in 70 of 70 such cells on the VIC report.
`changes` lists what rules 1 and 3 and steps 3 and 4 did, in output row numbers. Every table has `mineru_rows`: for
each output row, the MinerU rows (after dropping empty columns) it was built from, in the second read for a table
that was read again; none for a row of step 4.
"""
import difflib, json, re, shutil, sys
from collections import Counter

from tables import coverage as K, flag_checks as checks
from tables.doc import accepted_rereads, gemini_tables, mineru_tables, ocr_page, page_numbers, table_pages, use
from tables.grid import (DASHES, amount_key, column_map, ctype, join_rows, nodiac, nws, parse_amount, roles, trim,
                         two_amounts)
from tables.identities import find_identities

SAME = 0.9  # ratio from which two texts (letters and digits, no diacritics, no unit line) count as the same print
GROUPED = re.compile(r"\(?-?\d{1,3}(?:[.,]\d{3})+\)?")  # an amount written in groups of three digits
NUM = re.compile(r"\(?\d{1,3}(?:\.\d{3})+\)?")
TEXT_ROLES = ("label", "text")
UNIT_RES = [
    re.compile(r"\(?\s*[ĐD]\w{1,2}n\s+v\w{1,2}\s+t\w{1,4}\s*(?:[:.]\s*(?:(?:[^\s()|:]+\s+)?(?:VND|VNĐ|đồng))?"
               r"|\s+(?:[^\s()|:]+\s+)?(?:VND|VNĐ|đồng))\s*\)?", re.I),
    re.compile(r"\(?\s*(?:Triệu|Nghìn|Ngàn|Tỷ)\s*(?:VND|VNĐ|đồng)\s*\)?", re.I),
]
UNIT_WORD = re.compile(r"(?:Triệu|Thệu|Nghìn|Ngàn|Tỷ)\s*(?:VND|VNĐ|đồng)", re.I)


def strip_unit(s):
    """(text without unit, unit or None)."""
    s0 = nws(s)
    unit = None
    out = s0
    for rx in UNIT_RES:
        m = rx.search(out)
        while m:
            u = UNIT_WORD.search(m.group(0))
            unit = unit or (u.group(0) if u else None)
            out = (out[:m.start()] + " " + out[m.end():])
            m = rx.search(out)
    return nws(out), unit


def key(s):
    return re.sub(r"[\W_]+", "", nodiac(strip_unit(s)[0]).lower())


def ratio(a, b):
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def spelling(m, g):
    """Rule 2: the text to keep for a cell MinerU reads as m and Gemini as g. A MinerU cell with no letter and no
    digit (empty, a dash, punctuation) keeps MinerU's characters: there is no print to correct."""
    if not re.search(r"[^\W_]", m):
        return m
    return nws(g) if ratio(key(m), key(g)) >= SAME else m


def own_part(g, left, m):
    """Gemini's text g for a cell that MinerU reads as m, whose MinerU neighbour on the left reads `left`. When Gemini
    reads the neighbour's text (an item number such as 'A.', 'ii)') as the start of this cell and MinerU does not,
    that start is not this cell's: it is cut off, with the marks and spaces after it. Otherwise g is returned."""
    kl = key(left)
    if not kl or not key(g).startswith(kl) or key(m).startswith(kl):
        return g
    for i in range(1, len(g) + 1):
        if key(g[:i]) == kl:
            return re.sub(r"^[\W_]+", "", g[i:])
    return g


def split_glued(tables):
    """Rule 1, in place. Returns the (table, row, column) of every cell that was split."""
    done = []
    for t, tb in enumerate(tables):
        rows = tb["rows"]
        for r in range(len(rows) - 1):
            for c, cell in enumerate(rows[r]):
                s = nws(cell)
                toks = NUM.findall(s)
                if len(toks) == 2 and two_amounts(s) and "".join(toks) == s.replace(" ", "") \
                        and not nws(rows[r + 1][c]):
                    rows[r][c], rows[r + 1][c] = toks
                    done.append((t, r, c))
    return done


def fix_separators(tables):
    """Rule 3, in place. The thousands separator of a table is the mark that its amounts with two or more marks of
    one kind use. Returns (table, row, column, MinerU text) of every cell changed."""
    done = []
    for t, tb in enumerate(tables):
        cells = [(r, c, nws(x)) for r, row in enumerate(tb["rows"]) for c, x in enumerate(row)]
        cells = [(r, c, s, re.findall(r"[.,]", s)) for r, c, s in cells if GROUPED.fullmatch(s)]
        votes = Counter(m[0] for *_, m in cells if len(m) > 1 and len(set(m)) == 1)
        if votes["."] == votes[","]:
            continue
        sep = max(votes, key=votes.get)
        for r, c, s, m in cells:
            if m[-1] == sep and len(set(m)) > 1:
                tb["rows"][r][c] = re.sub(r"[.,]", sep, s)
                done.append((t, r, c, s))
    return done


def group_above(rows, r, c):
    """Amounts of column c in the rows directly above row r, up to the first cell that is not an amount or a dash."""
    out = []
    for row in reversed(rows[:r]):
        v = parse_amount(nws(row[c]))
        if v is None:
            break
        out.append(v)
    return out


def total_row(rows, role, r, g, cmap):
    """Step 4: the row to add under row r of a MinerU table for Gemini row g, which MinerU has no row for, or None.
    Only amounts are taken (Gemini gives an unlabelled total a name of its own), and only when each one is the sum
    of the amounts directly above it in its column. The total of a single row repeats that row, which is also what
    a reader that writes one line twice gives: it is taken only in a table where MinerU has a total of several
    rows. cmap: MinerU column -> Gemini column."""
    values = [c for c, ro in enumerate(role) if ro == "value"]
    new, single = [""] * len(role), False
    for c in values:
        s = nws(g[cmap[c]]) if c in cmap else ""
        if not s:
            continue
        group = group_above(rows, r + 1, c)
        if parse_amount(s) is None or not group or sum(group) != parse_amount(s):
            return None
        single |= len(group) == 1
        new[c] = s

    def proven(i, c):
        group = group_above(rows, i, c)
        return len(group) > 1 and sum(group) == parse_amount(nws(rows[i][c]))
    if not any(new) or single and not any(proven(i, c) for i in range(r + 1) for c in values):
        return None
    return new


def m_amounts(M, R, t, r):
    """The amounts of MinerU row (t, r) that the join uses: its value columns; none for a header row."""
    return () if r in R[t]["header_rows"] else \
        amount_key([M[t]["rows"][r][c] for c, ro in enumerate(R[t]["role"]) if ro == "value"])


def g_amounts(G, t, r):
    return () if r == 0 else amount_key(G[t]["rows"][r][len(G[t]["fields"]):])


def join(M, G):
    """Page-order row lists and the v1 join. Returns mref, gref, {MinerU index: (Gemini index, how)}."""
    R = [roles(t["rows"]) for t in M]
    mref = [(t, r) for t, tb in enumerate(M) for r in range(len(tb["rows"]))]
    gref = [(t, r) for t, tb in enumerate(G) for r in range(len(tb["rows"]))]
    km = [m_amounts(M, R, t, r) for t, r in mref]
    kg = [g_amounts(G, t, r) for t, r in gref]
    return mref, gref, join_rows(km, kg)


def value_flags(t, r, c, m, g):
    """Flags of a value cell of a joined body row, MinerU m and Gemini g: amount_mismatch when their amounts differ;
    blank_or_dash when MinerU leaves the cell empty and Gemini has a dash. Nothing is changed."""
    vm, vg = parse_amount(nws(m)), parse_amount(nws(g))
    if (vm or vg) and vm != vg:
        return [{"table": t, "row": r, "col": c, "kind": "amount_mismatch", "mineru": m, "gemini": g}]
    if not nws(m) and nws(g) in DASHES:
        return [{"table": t, "row": r, "col": c, "kind": "blank_or_dash", "mineru": m, "gemini": g}]
    return []


def same_print(mrow, grow):
    """Do two rows show the same print, whatever the order of their cells? Letters and digits of the whole row, cells
    in page order or in sorted order, at ratio SAME or more."""
    a, b = [key(x) for x in mrow if key(x)], [key(x) for x in grow if key(x)]
    return bool(a) and max(ratio("".join(a), "".join(b)), ratio("".join(sorted(a)), "".join(sorted(b)))) >= SAME


def text_join(M, G, J):
    """Step 3b, after steps 1 to 3. J: {(t, r): (Gemini index, how)}. A MinerU row with no amount that is still not
    joined takes the next free Gemini row with no amount, in page order, that shows the same print (same_print).
    Page order holds: the Gemini row lies after the Gemini rows of every joined MinerU row above and before those of
    every joined row below. Returns J with these rows added, how 'text'."""
    R = [roles(t["rows"]) for t in M]
    order = [(t, r) for t, tb in enumerate(M) for r in range(len(tb["rows"]))]
    gref = [(t, r) for t, tb in enumerate(G) for r in range(len(tb["rows"]))]
    J, used = dict(J), {j for j, _ in J.values()}
    for i, (t, r) in enumerate(order):
        if (t, r) in J or m_amounts(M, R, t, r):
            continue
        lo = max((J[k][0] for k in order[:i] if k in J), default=-1)
        hi = min((J[k][0] for k in order[i + 1:] if k in J), default=len(gref))
        for j in range(lo + 1, hi):
            gt, gr = gref[j]
            if j not in used and not g_amounts(G, gt, gr) and same_print(M[t]["rows"][r], G[gt]["rows"][gr]):
                J[t, r] = (j, "text"); used.add(j)
                break
    return J


def column_maps(M, G, mref, gref, J):
    """{(MinerU table, Gemini table): column map}, voted from the rows joined by amounts, else by text, else all."""
    groups = {}
    for i, (j, how) in J.items():
        groups.setdefault((mref[i][0], gref[j][0]), []).append((mref[i][1], gref[j][1], how))
    return {k: column_map(M[k[0]]["rows"], G[k[1]]["rows"], [(a, b) for a, b, h in v if h == "amounts"]
                          or [(a, b) for a, b, h in v if h == "text"] or [(a, b) for a, b, _ in v])
            for k, v in groups.items()}


def fits(rows, grow, cmap, free):
    """Do MinerU rows (top to bottom), read as one row, show Gemini row `grow`? Every column must reach SAME and
    every cell of every row must raise the ratio of its column (a short stray line added to a long label still
    reaches SAME; it is refused because the label fits better without it). `free`: Gemini columns with unknown
    content. Returns the sum of the column ratios, or None."""
    total = 0.0
    if any(nws(x).endswith(":") for r in rows[:-1] for x in r):
        return None
    used = [False] * len(rows)
    for c in range(len(rows[0])):
        cells = [nws(r[c]) for r in rows]
        k = cmap.get(c)
        if k in free:
            continue
        if k is None:
            if any(key(x) for x in cells):
                return None
            continue
        g = key(grow[k])
        full = ratio(key(" ".join(x for x in cells if x)), g)
        if full < SAME:
            return None
        total += full
        for i, x in enumerate(cells):
            if not key(x):
                continue
            used[i] = True
            if len(rows) > 1 and ratio(key(" ".join(y for n, y in enumerate(cells) if y and n != i)), g) >= full:
                return None
    return total if all(used) else None


def regroup(M, G, mref, gref, J, cmaps):
    """Step 3. Returns (blocks, cuts): blocks = [(MinerU indices top to bottom, Gemini index)] for runs read as
    one row; cuts = [(MinerU index, column, offset, Gemini index of the new row)]."""
    mrow = lambda i: M[mref[i][0]]["rows"][mref[i][1]]
    grow = lambda j: G[gref[j][0]]["rows"][gref[j][1]]
    text_only = lambda i: not any(ctype(x) in ("amount", "dash", "pct") for x in mrow(i))
    free = lambda j: set(range(len(G[gref[j][0]]["fields"]))) if gref[j][1] == 0 else set()
    taken = {j for j, _ in J.values()}
    block = {}  # MinerU index of a joined row -> the indices read as that row so far
    blocks, cuts = [], []
    pairs = sorted((i, j) for i, (j, how) in J.items() if how == "amounts")
    for (i0, j0), (i1, j1) in zip([(-1, -1)] + pairs, pairs + [(len(mref), len(gref))]):
        src = [i for i in range(i0 + 1, i1) if i not in J]
        gap = [j for j in range(j0 + 1, j1) if j not in taken]
        if not all(text_only(i) for i in src):
            continue
        tgt = ([("above", j0)] if i0 >= 0 else []) + [("gap", j) for j in gap] + ([("below", j1)] if i1 < len(mref) else [])

        def fit(a, b, n):
            kind, j = tgt[n]
            if kind == "above" and a != 0 or kind == "below" and b != len(src):
                return None
            rows = src[a:b]
            if kind == "above":
                rows = block.get(i0, [i0]) + rows
            elif kind == "below":
                rows = rows + [i1]
            if len({mref[i][0] for i in rows}) != 1 or (mref[rows[0]][0], gref[j][0]) not in cmaps:
                return None
            return fits([mrow(i) for i in rows], grow(j), cmaps[mref[rows[0]][0], gref[j][0]], free(j))

        best = {(0, 0): ((0, 0.0), None)}  # (MinerU rows used, Gemini rows passed) -> ((rows placed, ratios), back)
        for a in range(len(src) + 1):
            for n in range(len(tgt) + 1):
                if (a, n) not in best:
                    continue
                (placed, total), _ = best[a, n]
                steps = [((a + 1, n), 0, 0.0, None)] if a < len(src) else []
                if n < len(tgt):
                    steps.append(((a, n + 1), 0, 0.0, None))
                    for b in range(a + 1, len(src) + 1):
                        s = fit(a, b, n)
                        if s is not None:
                            steps.append(((b, n + 1), b - a, s, (a, b, n)))
                for to, d, s, step in steps:
                    new = (placed + d, total + s)
                    if to not in best or new > best[to][0]:
                        best[to] = (new, ((a, n), step))
        at, filled = (len(src), len(tgt)), set()
        while best[at][1]:
            at, step = best[at][1]
            if step:
                a, b, n = step
                kind, j = tgt[n]
                filled.add(n)
                if kind == "above":
                    block[i0] = block.get(i0, [i0]) + src[a:b]
                elif kind == "below":
                    block[i1] = src[a:b] + [i1]
                else:
                    blocks.append((src[a:b], j))
        for n, (kind, j) in enumerate(tgt):  # a Gemini row nothing was read as: is it the tail of the label above?
            g = grow(j)
            head = next((i for i, (jj, _) in J.items() if jj == j - 1), None)
            if kind != "gap" or n in filled or head is None or gref[j][0] != gref[j - 1][0] or any(key(x) for x in g[1:]):
                continue
            cm = cmaps.get((mref[head][0], gref[j][0]), {})
            col = next((c for c, k in cm.items() if k == 0), None)
            if col is None:
                continue
            m, a, b = nws(mrow(head)[col]), key(grow(j - 1)[0]), key(g[0])
            if not (a and b) or ratio(key(m), a + b) < SAME or ratio(key(m), a) >= SAME:
                continue
            cut = max(range(1, len(m)), key=lambda x: ratio(key(m[:x]), a) + ratio(key(m[x:]), b))
            cuts.append((head, col, cut, j))
    return blocks + [(v, J[i][0]) for i, v in block.items() if len(v) > 1], cuts


def apply_regroup(M, mref, J, blocks, cuts):
    """New MinerU tables, the join in (table, row) terms {(t, r): (Gemini index, how)}, {old index: (t, r)} and
    the list of changes."""
    first = {rows[0]: (rows, j) for rows, j in blocks}
    inside = {i for rows, _ in blocks for i in rows[1:]}
    cut = {i: (c, x, j) for i, c, x, j in cuts}
    out = [dict(tb, rows=[]) for tb in M]
    newjoin, where, changes = {}, {}, []
    for i, (t, r) in enumerate(mref):
        if i in inside:
            continue
        rows, j = first.get(i, ([i], J[i][0] if i in J else None))
        cells = [[nws(M[t]["rows"][mref[k][1]][c]) for k in rows] for c in range(len(M[t]["rows"][r]))]
        new = [" ".join(x for x in col if x) for col in cells] if len(rows) > 1 else list(M[t]["rows"][r])
        at = (t, len(out[t]["rows"]))
        for k in rows:
            where[k] = at
        if j is not None:
            newjoin[at] = (j, "regroup" if len(rows) > 1 or i not in J else J[i][1])
        if len(rows) > 1:
            changes.append({"kind": "rows_merged", "table": t, "row": at[1], "mineru_rows": [mref[k][1] for k in rows]})
        if len(rows) == 1 and i in cut:
            c, x, j2 = cut[i]
            s = nws(new[c])
            new[c] = s[:x].strip()
            out[t]["rows"].append(new)
            out[t]["rows"].append([s[x:].strip() if k == c else "" for k in range(len(new))])
            newjoin[t, at[1] + 1] = (j2, "regroup")
            changes.append({"kind": "row_split", "table": t, "row": at[1], "col": c})
        else:
            out[t]["rows"].append(new)
    return out, newjoin, where, changes


def with_rereads(raw, accepted):
    """raw: MinerU's tables of a page as read; accepted: {index in raw (str): {"rows", "bbox"}}, the second reads that
    reread.py accepted for this page. Returns (the tables with the second reads in place, after trim; output
    indexes of the tables that are second reads). A second read keeps the first read's title."""
    tabs = [dict(tb, rows=a["rows"], bbox=a["bbox"]) if (a := accepted.get(str(i))) else tb for i, tb in enumerate(raw)]
    second = [id(tb) for i, tb in enumerate(tabs) if str(i) in accepted]
    M = trim(tabs)
    return M, [t for t, tb in enumerate(M) if id(tb) in second]


def run_page(p, regrouping=True):
    M, reread = with_rereads(mineru_tables(p), accepted_rereads(p))
    G = gemini_tables(p) or []
    glued = split_glued(M)
    separators = fix_separators(M)
    mref, gref, J = join(M, G)
    cmaps = column_maps(M, G, mref, gref, J)
    blocks, cuts = regroup(M, G, mref, gref, J, cmaps) if regrouping else ([], [])
    M, J, where, changes = apply_regroup(M, mref, J, blocks, cuts)
    J = text_join(M, G, J)
    order = [(t, r) for t, tb in enumerate(M) for r in range(len(tb["rows"]))]
    voted = column_maps(M, G, order, gref, {order.index(k): v for k, v in J.items()})
    amounts = {(t, gref[j][0]) for (t, _), (j, how) in J.items() if how == "amounts"}
    texts = {(t, gref[j][0]) for (t, _), (j, how) in J.items() if how == "text"}
    cmaps |= {k: voted[k] for k in texts - amounts}  # a pair with no amount-joined row: voted from its text rows
    changes += [{"kind": "split_glued", "table": t, "row": where[mref.index((t, r))][1], "col": c} for t, r, c in glued]
    changes += [{"kind": "separator_fixed", "table": t, "row": where[mref.index((t, r))][1], "col": c, "mineru": s}
                for t, r, c, s in separators]
    R = [roles(t["rows"]) for t in M]
    source_rows = [[[] for _ in tb["rows"]] for tb in M]  # output row -> the MinerU rows it was built from
    for k, (t, r) in sorted(where.items()):
        source_rows[t][r].append(mref[k][1])
    for ch in changes:
        if ch["kind"] == "row_split":
            source_rows[ch["table"]][ch["row"] + 1] = list(source_rows[ch["table"]][ch["row"]])
    # digit vote: a MinerU amount box OCR reads nowhere, against box OCR and Gemini (checks.digit_vote)
    lines = ocr_page(p)
    extra, gem, fixed = K.alarms(lines, M)[0], K.held(G), set()
    unread = set(K.unread(lines, M)) if lines else set()
    for t, tb in enumerate(M):
        for r, row in enumerate(tb["rows"]):
            for c, m in enumerate(row):
                if K.amounts(m) == [re.sub(r"\D", "", m)] and K.amounts(m)[0] in unread:
                    new = checks.digit_vote(m, extra, gem)
                    if new:
                        row[c] = new
                        extra[re.sub(r"\D", "", new)] -= 1
                        extra = +extra
                        fixed.add((t, r, c))
                        changes.append({"kind": "digit_fixed", "table": t, "row": r, "col": c, "mineru": m, "ocr": new})
    flags, tables = [], []
    for t, tb in enumerate(M):
        role = R[t]["role"]
        out_rows, src = [], []
        for r, row in enumerate(tb["rows"]):
            new, s = list(row), ["ocr+gemini" if (t, r, c) in fixed else "mineru" for c in range(len(row))]
            hit = J.get((t, r))
            if hit is None:
                flags.append({"table": t, "row": r, "col": None, "kind": "row_not_joined"})
            for c, m in enumerate(row):
                if role[c] == "value" and r not in R[t]["header_rows"] and checks.flag_malformed(m):
                    flags.append({"table": t, "row": r, "col": c, "kind": "malformed", "mineru": m})
                if hit is None:
                    continue
                gt, gr = gref[hit[0]]
                k = cmaps.get((t, gt), {}).get(c)
                if k is None:
                    continue
                g = G[gt]["rows"][gr][k]
                if role[c] == "value" and r not in R[t]["header_rows"]:
                    flags += value_flags(t, r, c, m, g)
                elif role[c] in TEXT_ROLES or r in R[t]["header_rows"]:  # a header cell is text in any column
                    g = own_part(g, row[c - 1] if c else "", m)
                    new[c] = spelling(m, g)
                    if new[c] != m:
                        s[c] = "gemini (text join)" if hit[1] == "text" else "gemini"
                    repeat = not nws(m) and any(key(tb["rows"][i][c]) == key(g) for i in range(r))
                    header = gr == 0 and k < len(G[gt]["fields"])
                    if key(m) != key(g) and not repeat and not header:
                        flags.append({"table": t, "row": r, "col": c, "kind": "text_diff", "mineru": m, "gemini": g})
            out_rows.append(new); src.append(s)
        # off by at most 1 per term: a report in millions rounds every line (as forms.sums)
        flags += [f for f in identity_flags(t, tb["rows"], R[t]) if abs(f["residual"]) > len(f["terms"])]
        tables.append({"title": tb["title"], "bbox": tb["bbox"], "header_rows": R[t]["header_rows"], "roles": role,
                       "rows": out_rows, "text_source": src, "mineru_rows": source_rows[t]})
    if regrouping:
        order = [(t, r) for t, tb in enumerate(M) for r in range(len(tb["rows"]))]
        at = {j: order.index(k) for k, (j, _) in J.items()}  # Gemini row -> page position of its MinerU row
        added = {}  # (table, MinerU row above) -> (the row to add, the Gemini row)
        for j, (gt, gr) in enumerate(gref):
            if j in at or not gr or not any(key(x) for x in G[gt]["rows"][gr]):
                continue
            lo = max((v for jj, v in at.items() if jj < j), default=-1)
            hi = min((v for jj, v in at.items() if jj > j), default=len(order))
            if hi - lo == 1:  # MinerU has no row of its own there (one that has is flagged row_not_joined)
                t, r = order[lo] if lo >= 0 else (None, None)
                g = G[gt]["rows"][gr]
                new = total_row(M[t]["rows"], R[t]["role"], r, g, cmaps[t, gt]) \
                    if (t, gt) in cmaps and (t, r) not in added else None
                if new:
                    added[t, r] = (new, g)
                else:
                    flags.append({"table": t, "row": r, "col": None, "kind": "gemini_only_row", "gemini": g})
        for (t, r), (new, g) in sorted(added.items(), reverse=True):  # bottom up: the rows above keep their numbers
            for f in flags + changes:
                if f["table"] == t and f["row"] is not None and f["row"] > r:
                    f["row"] += 1
            tables[t]["rows"].insert(r + 1, new)
            tables[t]["text_source"].insert(r + 1, ["gemini" if x else "mineru" for x in new])
            tables[t]["mineru_rows"].insert(r + 1, [])
            changes.append({"kind": "row_added", "table": t, "row": r + 1, "gemini": g})
    how = [h for _, h in J.values()]
    changes += [{"kind": "table_reread", "table": t} for t in reread]
    flags += checks.page_flags(tables, lines)
    return {"page": p, "tables": tables, "flags": flags, "changes": changes,
            "rows_joined": {k: how.count(k) for k in ("amounts", "position", "regroup", "text")}
            | {"total": sum(len(t["rows"]) for t in M)}}


def identity_flags(t, rows, R):
    vcols = [c for c, ro in enumerate(R["role"]) if ro == "value"]
    body = [r for r in range(len(rows)) if r not in R["header_rows"]]
    if not vcols or not body:
        return []
    view = {"columns": [R["headers"][c] for c in vcols],
            "rows": [{"code": nws(rows[r][R["code"]]) if R["code"] is not None else None} for r in body]}
    values = [[parse_amount(nws(rows[r][c])) for c in vcols] for r in body]
    out = []
    for i in find_identities(view, values):
        if i["residual"] != 0:
            br, bc = i["target"]
            out.append({"table": t, "row": body[br], "col": vcols[bc], "kind": "identity_fail",
                        "identity": i["kind"], "residual": i["residual"],
                        "terms": [[body[a], vcols[b]] for (a, b), _ in i["terms"]]})
    return out


def main(folder):
    out = use(folder) / "tables"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    res = {p: run_page(p) for p in table_pages()}
    for p in sorted(set(page_numbers()) - set(res)):  # amounts box OCR reads on a page no reader found a table on
        more = checks.page_flags([], ocr_page(p))
        if more:
            res[p] = {"page": p, "tables": [], "flags": more, "changes": [], "rows_joined": {}}
    pages = {p: r["tables"] for p, r in res.items()}
    statements = checks.statement_tables(pages)  # their sums are checked by their form, not by discovery
    for p, more in checks.document_flags(pages).items():
        res[p]["flags"] += more
    tot = {}
    for p, r in res.items():
        r["flags"] = [f for f in r["flags"] if f["kind"] != "identity_fail" or (p, f["table"]) not in statements]
        (out / f"p{p:02d}.json").write_text(json.dumps(r, ensure_ascii=False, indent=0))
        for f in r["flags"] + r["changes"]:
            tot[f["kind"]] = tot.get(f["kind"], 0) + 1
        for k, v in r["rows_joined"].items():
            tot["rows_" + k] = tot.get("rows_" + k, 0) + v
    print(tot)


if __name__ == "__main__":
    main(sys.argv[1])
