"""Stage 4: Gemini reads the tables of every page where MinerU found a table -> <doc>/gemini/pNN.json.

usage: python -m tables.gemini_read <doc> [cap]      GEMINI_API_KEY from the environment or from .env at the repository root

Input is the upright page image only; Gemini never sees MinerU's output, so the two reads stay independent.
One call per page, never repeated: every call is written to <doc>/gemini/requests.json before it is made, and the
calls in that ledger are capped (default 100).
"""
import json, os, pathlib, re, sys, time

from google import genai
from google.genai import types

from tables.doc import page_png, table_pages, use
from tables.grid import parse_amount

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


def pick_model(client):
    names = []
    for m in client.models.list():
        n = m.name.split("/")[-1]
        acts = m.supported_actions or []
        if "flash" in n and "generateContent" in acts and not re.search(r"lite|image|tts|live|audio|preview|exp|latest", n):
            names.append(n)
    def ver(n):
        return tuple(int(x) for x in re.findall(r"\d+", n.split("flash")[0]))
    names.sort(key=ver)
    return names[-1], names


def thinking_for(model):
    major = int(re.search(r"gemini-(\d+)", model).group(1))
    if major >= 3:
        return types.ThinkingConfig(thinking_level="low")  # "minimal" rejected (400) by gemini-3.8-flash
    return types.ThinkingConfig(thinking_budget=0)


def summarize(tables):
    rows = sum(len(t["rows"]) for t in tables)
    nums = sum(parse_amount(c) is not None for t in tables for r in t["rows"] for c in r["cells"])
    return len(tables), rows, nums


def main(folder, cap):
    OUT = use(folder) / "gemini"
    LEDGER = OUT / "requests.json"
    OUT.mkdir(parents=True, exist_ok=True)
    todo = [p for p in table_pages() if not (OUT / f"p{p:02d}.json").exists()]
    print("pages to read:", len(todo), todo)
    used = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    client = genai.Client(api_key=api_key())
    model, _ = pick_model(client)
    print("model:", model)
    for p in todo:
        if len(used) >= cap:
            print("cap reached; stop"); break
        if any(u["page"] == p for u in used):
            print(p, "already requested once; not repeated"); continue
        used.append({"page": p, "t": time.time()}); LEDGER.write_text(json.dumps(used))
        cfg = types.GenerateContentConfig(
            temperature=0, response_mime_type="application/json", response_json_schema=SCHEMA,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH, thinking_config=thinking_for(model))
        img = types.Part.from_bytes(data=page_png(p).read_bytes(), mime_type="image/png")
        try:
            r = client.models.generate_content(model=model, contents=[img, PROMPT], config=cfg)
            tables = json.loads(r.text)["tables"]
        except Exception as e:
            print(p, "FAILED", type(e).__name__, str(e)[:300], flush=True); continue
        u = r.usage_metadata
        usage = {"in": u.prompt_token_count, "out": u.candidates_token_count,
                 "thoughts": u.thoughts_token_count, "total": u.total_token_count}
        (OUT / f"p{p:02d}.json").write_text(json.dumps({"model": model, "usage": usage, "raw": r.text, "tables": tables},
                                                       ensure_ascii=False, indent=1))
        print(p, summarize(tables), usage, flush=True)
    print("requests:", len(used))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 100)
