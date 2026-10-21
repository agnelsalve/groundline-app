"""Copy the A4 Groundline data into the app.

Joins the cleaned dataset with the AI judgments in the analysis cache, keeps only
the fields the app needs, and copies each verified source's pass/fail manifest.
Run once from the app folder:  python scripts/build_data.py
"""
import json
import pathlib
import sys

APP = pathlib.Path(__file__).resolve().parents[1]
A4 = APP.parents[1].parent / "Assignment 4" / "groundline-intelligence"
if len(sys.argv) > 1:
    A4 = pathlib.Path(sys.argv[1])

KEEP = ["record_id", "published_date", "title", "summary", "source_name", "source_type",
        "collected_via", "signal_type", "url", "discussion_url", "engagement_points"]
JUDGED = ["relevance", "entity", "sentiment", "theme", "evidence", "risk_to_weave",
          "opportunity_for_weave", "archetype", "key_fact", "why"]

dataset = json.loads((A4 / "data/clean/groundline_dataset.json").read_text(encoding="utf-8"))
cache = json.loads((A4 / "data/cache/analysis_cache.json").read_text(encoding="utf-8"))["analysis"]

records, missing = [], 0
for r in dataset:
    hit = cache.get(r["record_id"])
    if not hit:
        missing += 1
        continue
    rec = {k: r.get(k, "") for k in KEEP}
    rec.update({k: hit["a"].get(k) for k in JUDGED})
    rec["judged_by"] = hit.get("by", "")
    records.append(rec)

out = APP / "data"
out.mkdir(exist_ok=True)
(out / "records.json").write_text(json.dumps(records, ensure_ascii=False, indent=0), encoding="utf-8")

manifests = []
for m in sorted((A4 / "data/verified").glob("*/manifest.json")):
    manifests.append(json.loads(m.read_text(encoding="utf-8")))
(out / "manifests.json").write_text(json.dumps(manifests, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"{len(records)} records written ({missing} had no AI judgment), {len(manifests)} source manifests")
