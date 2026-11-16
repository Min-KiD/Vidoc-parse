"""One document folder and the readers' files in it. Every script takes the folder as its first argument and calls
`use(folder)` before anything else.

  <doc>/pages/pNN.png        upright page images, 200 dpi (stage 1)
  <doc>/ocr/pNN.json         box OCR lines {text, x0, x1, y0, y1} of the upright page (stage 1)
  <doc>/mineru/pNN.md        MinerU's page: markdown with HTML tables (stage 2)
  <doc>/mineru/pNN.raw.json  MinerU's blocks with boxes (stage 2)
  <doc>/mineru/reread.json   second reads accepted by reread.py (stage 3)
  <doc>/gemini/pNN.json      Gemini's tables (stage 4)
  <doc>/tables/pNN.json      the workflow's tables and flags (stage 5)
"""
import json, pathlib, re

from tables.grid import md_grids

DOC = None


def use(folder):
    global DOC
    DOC = pathlib.Path(folder).resolve()
    return DOC


def page_numbers():
    return sorted(int(f.stem[1:]) for f in (DOC / "pages").glob("p*.png"))


def page_png(p):
    return DOC / "pages" / f"p{p:02d}.png"


def page_size(p):
    import cv2
    h, w = cv2.imread(str(page_png(p)), cv2.IMREAD_GRAYSCALE).shape
    return w, h


def table_pages():
    """Pages where MinerU wrote a table."""
    out = []
    for p in page_numbers():
        f = DOC / "mineru" / f"p{p:02d}.md"
        t = f.read_text() if f.exists() else ""
        if "<table" in t or re.search(r"(?m)^\|\s*:?-{3,}", t):
            out.append(p)
    return out


def mineru_tables(p):
    """Every table in MinerU's page, with its box in pixels of the upright page image (None when MinerU's blocks and
    tables do not pair up one to one)."""
    d = DOC / "mineru"
    tabs = [t for t in md_grids((d / f"p{p:02d}.md").read_text()) if t["rows"]]
    raw = json.loads((d / f"p{p:02d}.raw.json").read_text())
    boxes = [b["bbox"] for b in raw["pages"][0]["blocks"] if b["type"] == "table"]
    w, h = page_size(p)
    boxes = [[b[0] * w, b[1] * h, b[2] * w, b[3] * h] for b in boxes]
    for i, t in enumerate(tabs):
        t["bbox"] = [round(x) for x in boxes[i]] if len(boxes) == len(tabs) else None
    return tabs


def accepted_rereads(p):
    """{index of the table among MinerU's tables of page p: {rows, bbox, case}} from reread.json."""
    f = DOC / "mineru" / "reread.json"
    return json.loads(f.read_text()).get(f"p{p:02d}", {}) if f.exists() else {}


def ocr_page(p):
    """Box OCR lines of the upright page, or [] when the page was not read."""
    f = DOC / "ocr" / f"p{p:02d}.json"
    return json.loads(f.read_text()) if f.exists() else []


def gemini_tables(p):
    """Gemini's tables of page p flattened to grids, or None when Gemini did not read the page. Field order per
    table: label, [code], [note], cells...; code/note columns exist only when some row has them. Row 0 is a header
    made from `columns`."""
    f = DOC / "gemini" / f"p{p:02d}.json"
    if not f.exists():
        return None
    out = []
    for t in json.loads(f.read_text())["tables"]:
        has_code = any(r.get("code") for r in t["rows"])
        has_note = any(r.get("note") for r in t["rows"])
        width = max([len(t.get("columns") or [])] + [len(r["cells"]) for r in t["rows"]])
        fields = ["label"] + (["code"] if has_code else []) + (["note"] if has_note else [])

        def flat(label, code, note, cells):
            row = [label] + ([code or ""] if has_code else []) + ([note or ""] if has_note else [])
            return row + list(cells) + [""] * (width - len(cells))
        rows = [flat("", "", "", t.get("columns") or [])] + [flat(r["label"], r.get("code"), r.get("note"), r["cells"])
                                                           for r in t["rows"]]
        out.append({"rows": rows, "title": t.get("title") or "", "fields": fields, "header_rows": [0]})
    return out
