"""Stage 6: what can be said about a document's tables without an answer key: one page of counts and every flag.
The flags are the ones the workflow wrote; this script only prints them.

usage: python -m tables.report <doc> > <doc>/report.md
"""
import json, sys
from collections import Counter

from tables import forms as F
from tables.doc import page_numbers, use
from tables.grid import ctype, nws


def listed(pages, kind, fields):
    out = []
    for p, d in pages.items():
        for f in d["flags"]:
            if f["kind"] == kind:
                where = f"p{p}" + "".join(f" {k[0]}{f[k]}" for k in ("table", "row", "col") if f[k] is not None)
                out.append(f"- {where}: " + ", ".join(f"{k} {f.get(k)!r}" for k in fields))
    return out or [f"- {kind}: none"]


def main(folder):
    d = use(folder)
    pages = {}
    for p in page_numbers():
        f = d / "tables" / f"p{p:02d}.json"
        pages[p] = json.loads(f.read_text()) if f.exists() else {"tables": [], "flags": [], "changes": []}
    tabs = {p: d["tables"] for p, d in pages.items()}
    print(f"# {d.name}: tables\n")
    kinds = Counter(ctype(c, "value" if ro == "value" and r not in t["header_rows"] else "other")
                    for T in tabs.values() for t in T for r, row in enumerate(t["rows"]) for c, ro in zip(row, t["roles"]))
    print(f"- pages {len(pages)}, with a table {sum(bool(T) for T in tabs.values())}, tables {sum(len(T) for T in tabs.values())}, "
          f"rows {sum(len(t['rows']) for T in tabs.values() for t in T)}, cells by kind {dict(kinds)}")
    joined = Counter()
    for d in pages.values():
        joined.update(d.get("rows_joined", {}))
    print(f"- rows: {dict(joined)}")
    print(f"- what the rules did: {dict(Counter(c['kind'] for d in pages.values() for c in d['changes']))}")
    flags = Counter(f["kind"] for d in pages.values() for f in d["flags"])
    print(f"- flags: {dict(flags)}")
    for kind in ("amount_mismatch", "blank_or_dash", "gemini_only_row", "malformed"):
        for p, d in pages.items():
            for f in d["flags"]:
                if f["kind"] == kind:
                    row = d["tables"][f["table"]]["rows"][f["row"]] if f["row"] is not None else []
                    print(f"  - {kind} p{p} t{f['table']} r{f['row']} c{f['col']}: MinerU {f.get('mineru')!r} Gemini {f.get('gemini')!r} | row {[nws(x)[:24] for x in row]}")

    _, where, _, unknown, _ = F.read(tabs)
    print(f"\n## Form sums\n\n- statement tables on pages {where}; form not known {unknown}")
    print("\n".join(listed(pages, "coded_row_empty", ("form", "code"))))
    print("\n".join(listed(pages, "form_sum_fail", ("form", "code", "printed", "parts_sum"))))
    print("\n".join(listed(pages, "statements_disagree", ("check",))))

    print("\n## Tables without a label column\n")
    print("\n".join(listed(pages, "no_label_column", ("rows_without_word", "rows_with_amount"))))

    print("\n## Coverage: amounts box OCR reads on a line of their own that no cell holds\n")
    print("\n".join(listed(pages, "amount_not_in_table", ("amount", "y", "text"))))

    print("\n## The other way: amounts of the cells that box OCR reads nowhere on the page\n")
    print("\n".join(listed(pages, "amount_unread", ("mineru",))))


if __name__ == "__main__":
    main(sys.argv[1])
