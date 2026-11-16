"""Stage 1, on the CPU, for any scanned PDF: upright page images and box OCR.

usage: python -m tables.prepare <pdf> <doc dir> [pages|ocr] [threads]
  pages: <doc dir>/pages/pNN.png      200 dpi render with the PDF's /Rotate applied, then turned upright
         <doc dir>/orientation.json   per page: quarter turns applied and the evidence for them
  ocr:   <doc dir>/ocr/pNN.json       PP-OCRv6 small (Vietnamese) text lines of the upright page
  Both by default. MinerU needs only the pages, so run_doc.sh starts it after `pages` and runs `ocr` beside it.

Orientation is two questions about the page itself, no page list and no orientation model:
  sideways?     text runs along the long side of its box, so the page lies sideways when most box length is vertical
  upside down?  the longest lines are read as they are and turned by 180 degrees; the better reading wins

threads: CPU threads for the OCR models. By default each process takes every core, so two runs side by side without
it are far slower than one after the other.
"""
import json, pathlib, sys

import cv2
import numpy as np

SAMPLE = 40  # lines read both ways for the upside-down question


def engine(threads=-1):
    """PP-OCRv6 small, Vietnamese, on onnxruntime: det 9.9 MB + rec 21 MB, fetched by rapidocr on first use."""
    from rapidocr import RapidOCR, OCRVersion, ModelType
    return RapidOCR(params={
        "Global.max_side_len": 4000, "Global.log_level": "warning",
        "Det.ocr_version": OCRVersion.PPOCRV6, "Rec.ocr_version": OCRVersion.PPOCRV6,
        "Det.model_type": ModelType.SMALL, "Rec.model_type": ModelType.SMALL,
        "Det.lang_type": "vi", "Rec.lang_type": "vi",
        "Det.limit_type": "max", "Det.limit_side_len": 4000,
        "EngineConfig.onnxruntime.intra_op_num_threads": threads})


def text_boxes(eng, img):
    """Detected text quads as (width, height, x0, y0, x1, y1)."""
    boxes = eng(img, use_det=True, use_cls=False, use_rec=False).boxes
    out = []
    for q in boxes if boxes is not None else []:
        q = np.asarray(q, dtype=float)
        w, h = np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[3] - q[0])
        out.append((w, h, q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()))
    return out


def quarter_turns(eng, img):
    """(k, evidence): np.rot90(img, k) is the upright page."""
    boxes = text_boxes(eng, img)
    vertical = sum(h for w, h, *_ in boxes if h > w)
    horizontal = sum(w for w, h, *_ in boxes if w >= h)
    k = 1 if vertical > horizontal else 0
    if k:
        img = np.rot90(img, 1)
        boxes = text_boxes(eng, img)
    lines = sorted((b for b in boxes if b[0] > b[1]), reverse=True)[:SAMPLE]
    score = [0.0, 0.0]
    for w, h, x0, y0, x1, y1 in lines:
        crop = np.ascontiguousarray(img[max(0, int(y0) - 2):int(y1) + 3, max(0, int(x0) - 2):int(x1) + 3])
        for turned in (0, 1):
            r = eng(np.ascontiguousarray(np.rot90(crop, 2)) if turned else crop, use_det=False, use_cls=False, use_rec=True)
            score[turned] += sum(r.scores or [])
    if score[1] > score[0]:
        k += 2
    return k, {"vertical": round(vertical), "horizontal": round(horizontal), "lines": len(lines),
               "as_is": round(score[0], 2), "turned_180": round(score[1], 2)}


def ocr_lines(eng, img):
    """Detection, line direction and recognition: RapidOCR's defaults, named because the engine keeps the flags of
    its last call."""
    r = eng(img, use_det=True, use_cls=True, use_rec=True)
    lines = []
    for box, txt in zip(r.boxes if r.boxes is not None else [], r.txts or []):
        xs, ys = [float(q[0]) for q in box], [float(q[1]) for q in box]
        lines.append({"text": txt, "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys)})
    return lines


def pages(eng, pdf, doc):
    """Every page rendered and turned upright. A page already in orientation.json is not turned again; when its image
    is missing (a cloned repository keeps the reads, not the images) it is rendered with the recorded turns."""
    import pymupdf
    (doc / "pages").mkdir(parents=True, exist_ok=True)
    log_file = doc / "orientation.json"
    log = json.loads(log_file.read_text()) if log_file.exists() else {}
    for n, page in enumerate(pymupdf.open(pdf), 1):
        name = f"p{n:02d}"
        if name in log and (doc / "pages" / f"{name}.png").exists():
            continue
        pix = page.get_pixmap(dpi=200, colorspace=pymupdf.csRGB, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)[:, :, ::-1]
        if name not in log:
            k, why = quarter_turns(eng, img)
            log[name] = {"turns": k, "pdf_rotate": page.rotation, **why}
            print(name, k, why, flush=True)
        cv2.imwrite(str(doc / "pages" / f"{name}.png"), np.ascontiguousarray(np.rot90(img, log[name]["turns"])))
        log_file.write_text(json.dumps(log, indent=0))


def ocr(eng, doc):
    """Box OCR of every upright page that has none yet."""
    (doc / "ocr").mkdir(exist_ok=True)
    for png in sorted((doc / "pages").glob("p*.png")):
        out = doc / "ocr" / f"{png.stem}.json"
        if not out.exists():
            out.write_text(json.dumps(ocr_lines(eng, cv2.imread(str(png))), ensure_ascii=False))


def main(pdf, doc, step="both", threads=-1):
    eng = engine(threads)
    if step in ("both", "pages"):
        pages(eng, pdf, doc)
    if step in ("both", "ocr"):
        ocr(eng, doc)


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), *sys.argv[3:4], *map(int, sys.argv[4:5]))
