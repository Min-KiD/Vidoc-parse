"""Stage 1, on the CPU, for any scanned PDF: upright page images and box OCR.

usage: python -m tables.prepare <pdf> <doc dir> [threads]
  <doc dir>/pages/pNN.png      200 dpi render with the PDF's /Rotate applied, then turned upright
  <doc dir>/ocr/pNN.json       PP-OCRv5 text lines of the upright page
  <doc dir>/orientation.json   per page: quarter turns applied and the evidence for them

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
    from rapidocr import RapidOCR, OCRVersion, ModelType
    return RapidOCR(params={
        "Global.max_side_len": 4000, "Global.log_level": "warning",
        "Det.ocr_version": OCRVersion.PPOCRV5, "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.MOBILE, "Rec.model_type": ModelType.MOBILE,
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


def main(pdf, doc, threads=-1):
    import pymupdf
    (doc / "pages").mkdir(parents=True, exist_ok=True)
    (doc / "ocr").mkdir(exist_ok=True)
    log_file = doc / "orientation.json"
    log = json.loads(log_file.read_text()) if log_file.exists() else {}
    eng = engine(threads)
    for n, page in enumerate(pymupdf.open(pdf), 1):
        name = f"p{n:02d}"
        if name in log and (doc / "ocr" / f"{name}.json").exists():
            if (doc / "pages" / f"{name}.png").exists():
                continue
            # the reads are kept (a cloned repository has them), the image is not: render it with the recorded turns
            pix = page.get_pixmap(dpi=200, colorspace=pymupdf.csRGB, alpha=False)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)[:, :, ::-1]
            cv2.imwrite(str(doc / "pages" / f"{name}.png"), np.ascontiguousarray(np.rot90(img, log[name]["turns"])))
            continue
        pix = page.get_pixmap(dpi=200, colorspace=pymupdf.csRGB, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)[:, :, ::-1]
        k, why = quarter_turns(eng, img)
        img = np.ascontiguousarray(np.rot90(img, k))
        cv2.imwrite(str(doc / "pages" / f"{name}.png"), img)
        (doc / "ocr" / f"{name}.json").write_text(json.dumps(ocr_lines(eng, img), ensure_ascii=False))
        log[name] = {"turns": k, "pdf_rotate": page.rotation, **why}
        log_file.write_text(json.dumps(log, indent=0))
        print(name, k, why, flush=True)


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), *map(int, sys.argv[3:4]))
