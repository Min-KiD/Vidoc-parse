"""Stage 4: Gemini reads the tables of every page where MinerU found a table -> <doc>/gemini/pNN.json.

usage: python -m tables.gemini_read <doc> [cap] [workers] [--follow]   GEMINI_API_KEY (and optionally GEMINI_MODEL)
from the environment or from .env at the repository root

Input is the upright page image only; Gemini never sees MinerU's output, so the two reads stay independent.
Pages are read in parallel (workers, default 8). Every call is written to <doc>/gemini/requests.json before it is
made; the calls in that ledger are capped (default 100). A call that fails or returns no text is retried, at most
ATTEMPTS calls per page counting earlier runs, so running the stage again only tries the pages still unread. A page
Gemini refuses (finish reason RECITATION) is not asked again in the same run. A rate-limit answer (429) is not a
read: the call waits the delay the error names and is counted neither against the cap nor against the page.
--follow: start before MinerU has finished; read each page as soon as MinerU's pNN.md shows a table, until
<doc>/mineru/.done exists.
"""
import json, os, pathlib, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

from google import genai
from google.genai import types

from tables.doc import table_pages, page_png, use
from tables.grid import parse_amount

MODEL = "gemini-3.8-flash"  # GEMINI_MODEL overrides; pinned so that a newly listed model does not change the output
ATTEMPTS = 3
BACKOFF = 10  # seconds per earlier call of the page, after a failed call
RATE_WAIT = 30  # seconds after a 429 whose error names no delay
RATE_WAITS = 10  # 429 answers one page may get before it is left unread

PROMPT = ('You are transcribing tables from one scanned page of a Vietnamese financial report. '
  'Return every table on the page, top to bottom. Copy each cell exactly as printed: keep dots, commas, '
  'parentheses, minus signs and percent signs. Do not calculate, round, translate or correct anything. '
  'Use "-" where the page prints a dash and "" where a cell is blank. `columns` lists only the value columns '
  '(the ones after the row label, the line code "Mã số" and the note reference "Thuyết minh"), left to right, '
  'header lines joined by one space. Each row has `label`, `code` (line code or null), `note` (note reference '
  'or null) and `cells` with exactly one string per column. Section header rows keep their label and get "" '
  'in every cell.')

SCHEMA = {"type": "object", "properties": {"tables": {"type": "array", "items": {
    "type": "object",
    "properties": {
        "title": {"type": "string"}, "unit": {"type": ["string", "null"]},
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "code": {"type": ["string", "null"]},
            "note": {"type": ["string", "null"]},
            "cells": {"type": "array", "items": {"type": "string"}}},
            "required": ["label", "code", "note", "cells"]}}},
    "required": ["title", "unit", "columns", "rows"]}}},
    "required": ["tables"]}


def api_key():
    """GEMINI_API_KEY from the environment, else from the .env file at the repository root."""
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    env = pathlib.Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        k, _, v = line.partition("=")
        if k.strip() == "GEMINI_API_KEY" and v.strip():
            return v.strip().strip("'\"")
    sys.exit("GEMINI_API_KEY is not set: put it in .env (see .env.example)")


def model_name():
    return os.environ.get("GEMINI_MODEL") or MODEL


def rate_delay(e):
    """Seconds to wait after a rate-limit error (HTTP 429), None for any other error."""
    if getattr(e, "code", None) != 429:
        return None
    m = re.search(r"retryDelay\W+(\d+)", str(e))
    return int(m.group(1)) if m else RATE_WAIT


def thinking_for(model):
    major = int(re.search(r"gemini-(\d+)", model).group(1))
    if major >= 3:
        return types.ThinkingConfig(thinking_level="low")  # "minimal" rejected (400) by gemini-3.8-flash
    return types.ThinkingConfig(thinking_budget=0)


def summarize(tables):
    rows = sum(len(t["rows"]) for t in tables)
    nums = sum(parse_amount(c) is not None for t in tables for r in t["rows"] for c in r["cells"])
    return len(tables), rows, nums


def finish(r):
    """Why Gemini stopped, for the log when it returned no text (MAX_TOKENS, SAFETY, ...)."""
    c = (r.candidates or [None])[0]
    return str(getattr(c, "finish_reason", None) or getattr(r, "prompt_feedback", None))


def main(folder, cap, workers=8, follow=False, client=None):
    d = use(folder)
    OUT = d / "gemini"
    LEDGER = OUT / "requests.json"
    OUT.mkdir(parents=True, exist_ok=True)
    used = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    client = client or genai.Client(api_key=api_key())
    model = model_name()
    print("model:", model, flush=True)
    cfg = types.GenerateContentConfig(
        temperature=0, response_mime_type="application/json", response_json_schema=SCHEMA,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH, thinking_config=thinking_for(model))
    lock = threading.Lock()

    def calls(p=None):
        return sum(not u.get("rate_limited") and (p is None or u["page"] == p) for u in used)

    def book(p):
        """One more call for page p, written to the ledger before it is made; None when the cap or the page's
        attempts are used up."""
        with lock:
            if calls() >= cap or calls(p) >= ATTEMPTS:
                return None
            u = {"page": p, "t": time.time()}
            used.append(u)
            LEDGER.write_text(json.dumps(used))
            return u

    def read(p):
        img = types.Part.from_bytes(data=page_png(p).read_bytes(), mime_type="image/png")
        waits = 0
        while u := book(p):
            try:
                r = client.models.generate_content(model=model, contents=[img, PROMPT], config=cfg)
                if r.text is None:
                    raise ValueError(f"no text, finish reason {finish(r)}")
                tables = json.loads(r.text)["tables"]
            except Exception as e:
                print(p, "FAILED", type(e).__name__, str(e)[:300], flush=True)
                delay = rate_delay(e)
                if delay is not None and waits < RATE_WAITS:
                    with lock:
                        u["rate_limited"] = True
                        LEDGER.write_text(json.dumps(used))
                    waits += 1
                    time.sleep(delay)
                    continue
                if "RECITATION" in str(e):  # Gemini's copy filter refuses this page; asking again gets the same answer
                    return False
                time.sleep(BACKOFF * calls(p))  # back off: lets server errors pass
                continue
            m = r.usage_metadata
            usage = {"in": m.prompt_token_count, "out": m.candidates_token_count,
                     "thoughts": m.thoughts_token_count, "total": m.total_token_count}
            (OUT / f"p{p:02d}.json").write_text(json.dumps(
                {"model": model, "usage": usage, "raw": r.text, "tables": tables}, ensure_ascii=False, indent=1))
            print(p, summarize(tables), usage, flush=True)
            return True
        return False

    sent = {}
    with ThreadPoolExecutor(workers) as pool:
        while True:
            last = not follow or (d / "mineru" / ".done").exists()  # looked at before the pages, so none is missed
            for p in table_pages():
                if p not in sent and not (OUT / f"p{p:02d}.json").exists():
                    sent[p] = pool.submit(read, p)
            if last:
                break
            time.sleep(1)
    missing = sorted(p for p, f in sent.items() if not f.result())
    print("pages read:", len(sent) - len(missing), "of", len(sent), "new")
    if missing:
        print("NOT READ", missing, "(call cap used up)" if calls() >= cap else "(refused or failed, see FAILED lines)")
    print("requests:", calls())


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--follow"]
    main(args[0], int(args[1]) if len(args) > 1 else 100, int(args[2]) if len(args) > 2 else 8,
         follow="--follow" in sys.argv)
