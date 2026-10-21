"""One brief, end to end: select -> write -> fact-check, with saved results as the backup.

Order of preference:
  1. live   - a fresh brief written and checked by two different AI models now
  2. saved  - the last brief Groundline wrote and checked for this exact request
  3. rules  - no AI at all: the top source articles listed without interpretation
"""
import datetime as dt
import json
import pathlib

import ai
import core

SAVED = core.DATA / "saved_briefs.json"


def load_saved():
    try:
        return json.loads(SAVED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(result):
    saved = load_saved()
    saved[core.request_key(result["request"])] = result
    SAVED.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")


def generate(req, use_ai=True, saved=None, progress=lambda msg: None):
    key = core.request_key(req)
    saved = load_saved() if saved is None else saved
    note = None
    if use_ai and ai.api_key():
        try:
            progress("writing")
            brief, writer = ai.write_brief(req, on_try=lambda m: progress(f"writing:{m}"))
            progress("checking")
            published, fc = ai.fact_check(brief, req, writer, on_try=lambda m: progress(f"checking:{m}"))
            return {"mode": "live", "request": req, "brief": published, "fact_check": fc, "written_by": writer,
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        except ai.AIUnavailable as e:
            note = str(e)
    elif use_ai:
        note = "No AI key is set up for this app."
    if key in saved:
        return {**saved[key], "mode": "saved", "note": note}
    return {"mode": "rules", "request": req, "brief": core.rules_brief(req), "written_by": "rules",
            "fact_check": {"status": "ai_offline", "groundedness": None, "log": []}, "note": note,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
