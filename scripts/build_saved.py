"""Write and fact-check the default briefs, and save them as the app's backup.

The app shows these when the AI is busy. Needs GEMINI_API_KEY in the environment.
Run from the app folder:  python scripts/build_saved.py [Weave Podium ...]
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import core      # noqa: E402
import pipeline  # noqa: E402

recs = core.load_records()
first, last = core.data_window(recs)
groups = list(core.SOURCE_GROUPS)
subjects = sys.argv[1:] or ["Weave", "Podium", "Birdeye", "Market"]
windows = [(last - dt.timedelta(days=90), last), (last - dt.timedelta(days=30), last)]

for s in subjects:
    for start, end in windows:
        try:
            req = core.build_request(recs, s, start, end, groups)
        except core.UserError as e:
            print(f"{s} {start}..{end}: skipped ({e})")
            continue
        res = pipeline.generate(req, use_ai=True, saved={}, progress=lambda m: print("  ", m))
        fc = res["fact_check"]
        print(f"{s} {start}..{end}: {res['mode']} by {res['written_by']}, checked by {fc.get('checker')}, "
              f"groundedness {fc.get('groundedness')} ({fc.get('status')}) {res.get('note') or ''}")
        if res["mode"] == "live":
            pipeline.save(res)
