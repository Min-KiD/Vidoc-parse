"""Stage 3: a second read of a flagged table. When the checks say a MinerU table is incomplete (an amount box OCR
reads on the page is in no cell, or the table has no label column), MinerU reads it again from a crop that holds
everything printed beside and under it, and the second read replaces the first when it is better.

usage: python -m tables.reread crops <doc>     -> <doc>/reread/pages/pNN_tK.png, crops.json
       bash tables/mineru/run_mineru.sh <doc>/reread  -> <doc>/reread/mineru/   (run_doc.sh does this)
       python -m tables.reread compare <doc>   -> <doc>/reread/compare.json
       python -m tables.reread accept <doc>    -> <doc>/mineru/reread.json, read by workflow.py

Crop of a flagged table: full page width; top = table top - 40 px; bottom = the lower of the table bottom and the
lowest flagged line of the table, + 40 px; never past the top of the next table that has no flag of its own.
"""
import json, sys

import cv2

from tables import coverage as K, doc, flag_checks as checks
from tables.doc import mineru_tables, ocr_page, page_png, table_pages
from tables.grid import md_grids, nws, parse_amount, trim, value

PAD = 40
KINDS = ("amount_not_in_table", "no_label_column", "amount_unread")


def flagged(p):
    """(MinerU tables of page p, OCR lines, {table: lowest bottom of its flagged OCR lines or None})."""
    tabs, lines = trim(mineru_tables(p)), ocr_page(p)
    out = {}
    for f in checks.page_flags(tabs, lines):
        if f["table"] is None or f["kind"] not in ("amount_not_in_table", "no_label_column"):
            continue
        low = out.get(f["table"])
        if f["kind"] == "amount_not_in_table":
            y1 = max(l["y1"] for l in lines if round(l["y0"]) == f["y"] and l["text"] == f["text"])
            low = max(low or 0, y1)
        out[f["table"]] = low
    return tabs, lines, out


def crops():
    d = doc.DOC / "reread"
    (d / "pages").mkdir(parents=True, exist_ok=True)
    meta = {}
    for p in table_pages():
        tabs, _, fl = flagged(p)
        if not fl:
            continue
        img = cv2.imread(str(page_png(p)), cv2.IMREAD_GRAYSCALE)
        h = img.shape[0]
        for t, low in sorted(fl.items()):
            if not tabs[t].get("bbox"):
                print(f"p{p} t{t}: no table box, no crop")
                continue
            x0, y0, x1, y1 = tabs[t]["bbox"]
            top, bottom = max(0, y0 - PAD), min(h, round(max(y1, low or 0)) + PAD)
            nxt = [tb["bbox"][1] for k, tb in enumerate(tabs) if k not in fl and tb.get("bbox") and tb["bbox"][1] > y0]
            if nxt:
                bottom = min(bottom, min(nxt))
            key = f"p{p:02d}_t{t}"
            cv2.imwrite(str(d / "pages" / f"{key}.png"), img[top:bottom])
            meta[key] = {"page": p, "table": t, "offset": [0, top], "size": [img.shape[1], bottom - top]}
            print(key, "rows", top, bottom)
    (d / "crops.json").write_text(json.dumps(meta, indent=1))


def second_read(d, key, size, top=0):
    """MinerU's tables of crop `key` as read (before trim), boxes in crop pixels moved down by `top`."""
    md, raw = d / "mineru" / f"{key}.md", d / "mineru" / f"{key}.raw.json"
    tabs = [t for t in md_grids(md.read_text()) if t["rows"]]
    boxes = [b["bbox"] for b in json.loads(raw.read_text())["pages"][0]["blocks"] if b["type"] == "table"]
    w, h = size
    for i, t in enumerate(tabs):
        t["bbox"] = [round(b * s) + o for b, s, o in zip(boxes[i], (w, h, w, h), (0, top, 0, top))] \
            if len(boxes) == len(tabs) else None
    return tabs


def reread_tables(d, key, size):
    return trim(second_read(d, key, size))


def pick(first, seconds):
    """Index of the table of the second read that holds most of the first read's amounts (more rows on a tie)."""
    have = K.held([first])
    return max(range(len(seconds)), key=lambda k: (sum((have & K.held([seconds[k]])).values()), len(seconds[k]["rows"])))


def case_tables(d, key, m):
    """(MinerU's page tables before trim, index of the flagged table among them, the second read before trim with
    page boxes, index of its table that stands for the flagged one)."""
    p, t = m["page"], m["table"]
    raw = mineru_tables(p)
    first = trim(raw)[t]  # trim keeps the table objects: find the flagged one among the raw tables
    i = next(x for x, tb in enumerate(raw) if tb is first)
    sraw = second_read(d, key, tuple(m["size"]), m["offset"][1])
    strim = trim(sraw)
    k = next(x for x, tb in enumerate(sraw) if tb is strim[pick(first, strim)])
    return mineru_tables(p), i, second_read(d, key, tuple(m["size"]), m["offset"][1]), k


def in_band(tabs, top, bottom):
    """Tables that start inside the band, moved to crop coordinates. A table that starts above the band is not in the
    crop; counting it would charge the re-read with amounts the crop never showed."""
    out = []
    for tb in tabs:
        b = tb.get("bbox")
        if b and top <= b[1] < bottom:
            out.append(dict(tb, bbox=[b[0], b[1] - top, b[2], b[3] - top]))
    return out


def words_first(tabs):
    """Rows with an amount whose first cell has a word (3 letters or more), over rows with an amount."""
    am = [r for tb in tabs for r in tb["rows"]
          if any(parse_amount(nws(value(x))) is not None and sum(ch.isdigit() for ch in x) >= 4 for x in r)]
    return sum(sum(ch.isalpha() for ch in nws(value(r[0]))) >= 3 for r in am), len(am)


def compare():
    d = doc.DOC / "reread"
    meta = json.loads((d / "crops.json").read_text())
    rows = []
    for key, m in sorted(meta.items()):
        p, t, top, (w, hh) = m["page"], m["table"], m["offset"][1], m["size"]
        tabs = trim(mineru_tables(p))
        lines = [dict(l, y0=l["y0"] - top, y1=l["y1"] - top) for l in ocr_page(p)
                 if l["y0"] >= top and l["y1"] <= top + hh]
        before = in_band(tabs, top, top + hh)
        if not (d / "mineru" / f"{key}.md").exists():
            rows.append({"case": key, "page": p, "table": t, "error": "no MinerU output for the crop"})
            continue
        after = reread_tables(d, key, (w, hh))
        fb = [f["kind"] for f in checks.page_flags(before, lines) if f["kind"] in KINDS]
        fa = [f["kind"] for f in checks.page_flags(after, lines) if f["kind"] in KINDS]
        lost = K.held(before) - K.held(after)
        rows.append({"case": key, "page": p, "table": t,
                     "flags_before": len(fb), "flags_after": len(fa),
                     "kinds_before": sorted(set(fb)), "kinds_after": sorted(set(fa)),
                     "shape_before": [f"{len(tb['rows'])}x{len(tb['rows'][0])}" for tb in before],
                     "shape_after": [f"{len(tb['rows'])}x{len(tb['rows'][0])}" for tb in after],
                     "lost": sum(lost.values()), "lost_amounts": sorted(lost),
                     "words_first_before": words_first(before), "words_first_after": words_first(after)})
    (d / "compare.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    for r in rows:
        print(r)


def verdict(r):
    if "error" in r:
        return "failed"
    if r["lost"] or r["flags_after"] > r["flags_before"]:
        return "worse"
    return "better" if r["flags_after"] < r["flags_before"] else "same"


def accept():
    """The second read replaces the first when it holds every amount the first held and has fewer flags (verdict
    `better`). Writes reread.json into MinerU's folder of the document: {pNN: {index of the table among MinerU's
    tables of the page as read: {rows: the second read's grid before trim, bbox: its box in page pixels, case}}}.
    A case without a second read on disk has no compare result `better` and is left out: the first read stands."""
    d = doc.DOC / "reread"
    meta = json.loads((d / "crops.json").read_text())
    comp = {r["case"]: r for r in json.loads((d / "compare.json").read_text())}
    out = {}
    for key, m in sorted(meta.items()):
        if key not in comp or verdict(comp[key]) != "better":
            continue
        _, i, sraw, k = case_tables(d, key, m)
        out.setdefault(f"p{m['page']:02d}", {})[str(i)] = {"rows": sraw[k]["rows"], "bbox": sraw[k]["bbox"], "case": key}
    f = doc.DOC / "mineru" / "reread.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"{f}: {sum(map(len, out.values()))} tables on pages {sorted(out)}")


if __name__ == "__main__":
    step, folder = sys.argv[1:3]
    doc.use(folder)
    {"crops": crops, "compare": compare, "accept": accept}[step]()
