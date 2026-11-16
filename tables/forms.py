"""The three main statements checked by their own form: line-code sums of B01, B02 and B03 (Circulars 200/2014 and
202/2014), the equalities between statements, and coded rows without a value. No answer key, no model, no page list.

A statement table is a table with a column headed 'Mã số'. Which statement it is: the form that lists most of its
line codes. Its values are the columns to the right of the line code, the item and the note.
"""
import re

from tables.grid import nodiac, nws, parse_amount, roles, value

CODE = re.compile(r"\d{2,3}[ab]?")


def codes(a, b):
    return [str(i).zfill(2) for i in range(a, b + 1)]


# total code -> parts; a part is a code (added) or (code, sign). A part the statement does not print is left out.
B01 = {"100": ["110", "120", "130", "140", "150"], "110": ["111", "112"], "120": ["121", "122", "123"],
       "130": codes(131, 139), "140": ["141", "149"], "150": codes(151, 155),
       "200": ["210", "220", "230", "240", "250", "260"], "210": codes(211, 219), "220": ["221", "224", "227"],
       "221": ["222", "223"], "224": ["225", "226"], "227": ["228", "229"], "230": ["231", "232"],
       "240": ["241", "242"], "250": codes(251, 255), "260": codes(261, 269), "270": ["100", "200"],
       "300": ["310", "330"], "310": codes(311, 324), "330": codes(331, 343), "400": ["410", "430"],
       "410": codes(411, 422) + ["429"], "411": ["411a", "411b"], "421": ["421a", "421b"], "430": ["431", "432"],
       "440": ["300", "400"]}
B02 = {"10": ["01", ("02", -1)], "20": ["10", ("11", -1)],
       "30": ["20", "21", ("22", -1), "24", ("25", -1), ("26", -1)], "40": ["31", ("32", -1)], "50": ["30", "40"],
       "60": ["50", ("51", -1), ("52", -1)]}
B02_SPLIT = {"60": ["61", "62"]}
B03 = {"08": codes(1, 7), "20": codes(8, 17), "30": codes(21, 27), "40": codes(31, 36), "50": ["20", "30", "40"],
       "70": ["50", "60", "61"]}
B03_DIRECT = {"20": codes(1, 7)}  # the direct method has no line 08
FORMULAS = {"B01": [B01], "B02": [B02, B02_SPLIT], "B03": [B03]}
LISTED = {st: {c for F in sets for total, parts in F.items() for c in [total] + [x if isinstance(x, str) else x[0] for x in parts]}
          for st, sets in FORMULAS.items()}
LISTED["B02"] |= {"23", "70", "71"}  # lines in no sum: interest expense, earnings per share


def columns(rows, head):
    """(line-code column, value columns) of a statement table, or None for any other table."""
    hdr = [" ".join(nodiac(rows[r][c]).lower() for r in head) for c in range(len(rows[0]))]
    code = next((c for c, h in enumerate(hdr) if re.search(r"\bma(\s*so)?\b", h)), None)  # MinerU also reads 'Mãsố'
    if code is None:
        return None
    note = next((c for c, h in enumerate(hdr) if "thuyet" in h), code)
    first = max(code, note, roles(rows)["label"]) + 1
    return code, list(range(first, len(rows[0])))


def statement_of(found, before):
    """The form that lists most of the line codes `found`, when it lists more than half of them. Two forms list
    equally many on a last page that only has lines 50 to 70: the table then continues `before`, the statement of
    the table before it."""
    n = {st: len(found & LISTED[st]) for st in LISTED}
    top = [st for st in n if n[st] == max(n.values()) and 2 * n[st] > len(found)]
    return top[0] if len(top) == 1 else before if before in top else None


def read(pages):
    """pages: {page: tables}; a table has `rows` and, from the workflow, `header_rows`.
    Returns ({form: {code: [value per value column]}}, {form: pages},
    coded rows without a value [(page, form, code, table, row)],
    statement tables whose form is not known [(page, table)], {(form, code): (page, table, row, [value columns])}).
    A code read twice keeps its last row, in V and in the places alike."""
    V, where, empty, unknown, st, place = {}, {}, [], [], None, {}
    for p, tables in sorted(pages.items()):
        for t, tb in enumerate(tables):
            rows = [[nws(value(c)) for c in row] for row in tb["rows"]]
            head = tb.get("header_rows", roles(rows)["header_rows"]) if rows else []
            cols = columns(rows, head) if head else None
            if cols is None:
                continue
            k, vals = cols
            coded, at = {}, {}
            for r, row in enumerate(rows):
                code = row[k].replace(" ", "")
                code = code.zfill(2) if code.isdigit() else code  # B02 and B03 print '1' for line 01
                if r not in head and CODE.fullmatch(code):
                    coded[code] = [row[c] for c in vals]
                    at[code] = r
            st = statement_of(set(coded), st)
            if st is None:
                unknown.append((p, t))
                continue
            where.setdefault(st, []).append(p)
            for code, cells in coded.items():
                V.setdefault(st, {})[code] = [parse_amount(x) for x in cells]
                place[st, code] = (p, t, at[code], vals)
                if not any(cells):
                    empty.append((p, st, code, t, at[code]))
    return V, {st: sorted(set(v)) for st, v in where.items()}, empty, unknown, place


def sums(V):
    """(sums checked, failures [(form, total code, value column, printed, sum of the parts)], cells under a passing
    sum {(form, code, column)}). A sum passes when it is off by at most 1 per part: a report in millions rounds
    every line. A deducted part is subtracted when the statement prints it as a plain number and added when the
    statement prints it as a negative, '(470.738.091)': either reading may hold."""
    n, fails, covered = 0, [], set()
    for st, sets in FORMULAS.items():
        S = V.get(st, {})
        for F in sets + ([B03_DIRECT] if st == "B03" and "08" not in S else []):
            for total, parts in F.items():
                parts = [(x, 1) if isinstance(x, str) else x for x in parts]
                parts = [(c, s) for c, s in parts if c in S]
                if total not in S or not parts:
                    continue
                for j, T in enumerate(S[total]):
                    if T is None:
                        continue
                    n += 1
                    here = [(S[c][j] or 0, s) for c, s in parts if j < len(S[c])]
                    got = sum(x * s for x, s in here)
                    if min(abs(got - T), abs(sum(x for x, _ in here) - T)) <= len(parts):
                        covered |= {(st, total, j)} | {(st, c, j) for c, _ in parts}
                    else:
                        fails.append((st, total, j, T, got))
    return n, fails, covered


def between(V):
    """Equalities between statements, as {name: holds}; only those whose lines were read. Columns as the forms
    order them: the balance sheet closes in its first value column and opens in its second, the cash-flow statement
    has this year first."""
    get = lambda st, code, j=None: (V.get(st, {}).get(code) or [None] * 9)[j] if j is not None else V.get(st, {}).get(code)
    out = {}
    if None not in (get("B03", "70", 0), get("B01", "110", 0)):
        out["cash at the end: B03 70 = B01 110, closing"] = get("B03", "70", 0) == get("B01", "110", 0)
    if None not in (get("B03", "60", 0), get("B01", "110", 1)):
        out["cash at the start: B03 60 = B01 110, opening"] = get("B03", "60", 0) == get("B01", "110", 1)
    if get("B03", "01") and get("B02", "50"):
        out["profit before tax: B03 01 is a column of B02 50"] = all(x in get("B02", "50") for x in get("B03", "01") if x is not None)
    return out
