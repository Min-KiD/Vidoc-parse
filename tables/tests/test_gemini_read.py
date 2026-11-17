"""Stage 4's call budget, with a fake Gemini client: no key, no network."""
import json, threading
from types import SimpleNamespace

import pytest

from tables import gemini_read

ANSWER = json.dumps({"tables": [{"title": "", "unit": None, "columns": ["2025"],
                                 "rows": [{"label": "Tiền", "code": None, "note": None, "cells": ["1.000"]}]}]})
USAGE = SimpleNamespace(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=None, total_token_count=2)


class RateLimited(Exception):
    code = 429


class FakeModels:
    """Answers every call, except the failures planned per page: a list of exceptions or None (no text)."""

    def __init__(self, plan=None):
        self.plan = {p: list(v) for p, v in (plan or {}).items()}
        self.calls = []
        self.lock = threading.Lock()

    def generate_content(self, model, contents, config):
        page = int(contents[0].inline_data.data.decode())
        with self.lock:
            self.calls.append(page)
            todo = self.plan.get(page) or []
            fail = todo.pop(0) if todo else "ok"
        if isinstance(fail, Exception):
            raise fail
        if fail is None:
            return SimpleNamespace(text=None, usage_metadata=USAGE,
                                   candidates=[SimpleNamespace(finish_reason="FinishReason.RECITATION")])
        return SimpleNamespace(text=ANSWER, usage_metadata=USAGE, candidates=[])


@pytest.fixture
def doc(tmp_path, monkeypatch):
    """A document of 20 pages, each with a table in MinerU's read; the page image holds the page number."""
    monkeypatch.setattr(gemini_read, "BACKOFF", 0)
    monkeypatch.setattr(gemini_read, "RATE_WAIT", 0)
    (tmp_path / "pages").mkdir()
    (tmp_path / "mineru").mkdir()
    for p in range(1, 21):
        (tmp_path / "pages" / f"p{p:02d}.png").write_bytes(str(p).encode())
        (tmp_path / "mineru" / f"p{p:02d}.md").write_text("<table><tr><td>1</td></tr></table>")
    return tmp_path


def run(doc, models, cap=100, workers=8):
    gemini_read.main(doc, cap, workers, client=SimpleNamespace(models=models))
    return sorted(int(f.stem[1:]) for f in (doc / "gemini").glob("p*.json"))


def test_cap_holds_with_more_workers_than_calls(doc):
    models = FakeModels()
    assert len(run(doc, models, cap=5, workers=8)) == 5
    assert len(models.calls) == 5


def test_failed_page_is_called_until_it_succeeds_within_its_attempts(doc):
    models = FakeModels({3: [ValueError("server error"), ValueError("server error")]})
    assert 3 in run(doc, models)
    assert models.calls.count(3) == 3


def test_page_that_keeps_failing_stops_at_its_attempts_across_runs(doc):
    models = FakeModels({3: [ValueError("e")] * 2})
    run(doc, models, workers=1)
    assert models.calls.count(3) == 3  # two failures and the read that worked
    models = FakeModels({4: [ValueError("e")] * 9})
    (doc / "gemini" / "p04.json").unlink(missing_ok=True)
    run(doc, models)
    assert models.calls.count(4) == 2  # one call was already spent on page 4 in the first run


def test_rerun_calls_only_unread_pages(doc):
    run(doc, FakeModels({7: [None]}))  # page 7 refused
    again = FakeModels()
    assert len(run(doc, again)) == 20
    assert again.calls == [7]


def test_refused_page_is_not_asked_again_in_the_same_run(doc):
    models = FakeModels({7: [None, None, None]})
    assert 7 not in run(doc, models)
    assert models.calls.count(7) == 1


def test_rate_limit_is_neither_a_page_attempt_nor_a_call_of_the_cap(doc):
    models = FakeModels({5: [RateLimited("429 RESOURCE_EXHAUSTED retryDelay: 0s")] * 4})
    assert len(run(doc, models, cap=20)) == 20
    assert models.calls.count(5) == 5
    ledger = json.loads((doc / "gemini" / "requests.json").read_text())
    assert sum(not u.get("rate_limited") for u in ledger) == 20
