"""Sums discovered in a table grid (row totals, column sums, line-code formulas), used for the identity_fail flag
on tables that are not statements. Statements are checked by their own form in forms.py."""
import re

BALANCE = {"100": "110+120+130+140+150", "110": "111+112", "120": "121+122+123",
  "130": "131+132+133+134+135+136+137+139", "140": "141+149", "150": "151+152+153+154+155",
  "200": "210+220+230+240+250+260", "210": "211+212+213+214+215+216+219", "220": "221+224+227",
  "221": "222+223", "224": "225+226", "227": "228+229", "230": "231+232", "240": "241+242",
  "250": "251+252+253+254+255", "260": "261+262+263+268+269", "270": "100+200",
  "300": "310+330", "400": "410+430", "440": "300+400"}
INCOME = {"10": "01-02", "20": "10-11", "30": "20+21-22+24-25-26", "40": "31-32", "50": "30+40", "60": "50-51-52"}
FORMULAS = {**BALANCE, **INCOME}

TOTAL_HDR = re.compile(r"(?i)^\s*(tổng cộng|tổng|cộng)\s*$")


def _ident(kind, target, terms, values, **extra):
    """terms: [((r,c), sign)]. residual = target - sum(sign*term)."""
    vals = {target: values[target[0]][target[1]]}
    for cell, _ in terms:
        vals[cell] = values[cell[0]][cell[1]]
    residual = vals[target] - sum(s * vals[cell] for cell, s in terms)
    return {"kind": kind, "target": target, "terms": terms, "residual": residual,
            "values": vals, **extra}


def _num(v):
    return v is not None


def _row_totals(table, values):
    cols = table["columns"]
    tc = next((c for c in range(len(cols) - 1, -1, -1) if TOTAL_HDR.match(cols[c] or "")), None)
    if tc is None or len(cols) < 3:
        return []
    out = []
    for r, row in enumerate(values):
        if sum(_num(v) for v in row) < 2 or not _num(row[tc]):
            continue
        terms = [((r, c), 1) for c in range(len(cols)) if c != tc and _num(row[c])]
        if terms:
            out.append(_ident("row_total", (r, tc), terms, values))
    return out


def _col_sums(table, values):
    n = len(table["columns"])
    need = max(1, n - 1)
    out = []
    for r in range(2, len(values)):
        best = None  # (holding, length, k)
        for k in range(0, r - 1):
            hold, nonzero = 0, False
            for c in range(n):
                t = values[r][c]
                block = [values[i][c] for i in range(k, r) if _num(values[i][c])]
                if t is None or not block:
                    continue
                s = sum(block)
                if s == t:
                    hold += 1
                    nonzero |= s != 0
            if hold >= need and nonzero:
                cand = (hold, r - k, k)
                if best is None or cand[:2] > best[:2]:
                    best = cand
        if best is None:
            continue
        k = best[2]
        for c in range(n):
            terms = [((i, c), 1) for i in range(k, r) if _num(values[i][c])]
            if _num(values[r][c]) and terms:
                out.append(_ident("col_sum", (r, c), terms, values))
    return out


def _parse_formula(f):
    return [(m.group(2), -1 if m.group(1) == "-" else 1) for m in re.finditer(r"([+-]?)(\d+)", f)]


def _code_formulas(table, values):
    rows = table["rows"]
    code_row = {}
    for r, row in enumerate(rows):
        code = (row.get("code") or "").strip()
        if code.isdigit() and len(code) == 1:
            code = code.zfill(2)  # income statement prints "1", "2"; formulas use "01", "02"
        if code and code not in code_row:
            code_row[code] = r
    codes_num = [int(c) for c in code_row if c.isdigit()]
    max_code = max(codes_num, default=-1)
    out = []
    for code, r in code_row.items():
        f = FORMULAS.get(code)
        if not f:
            continue
        terms_codes = _parse_formula(f)
        if any(tc not in code_row and int(tc) >= max_code for tc, _ in terms_codes):
            continue  # incomplete: statement may continue on another page
        for c in range(len(table["columns"])):
            if not _num(values[r][c]):
                continue
            terms = [((code_row[tc], c), s) for tc, s in terms_codes
                     if tc in code_row and _num(values[code_row[tc]][c])]
            out.append(_ident("code_formula", (r, c), terms, values, code=code))
    return out


def find_identities(table, values):
    return _row_totals(table, values) + _col_sums(table, values) + _code_formulas(table, values)
