"""Groundline core: the verified records, the filters, and every number in a brief.

Ported from the A4 n8n workflow (23_brief_writer.js). Numbers are never left to the
AI: counts, tone and share are computed here and handed to the writer as STATS.
"""
import datetime as dt
import json
import pathlib
from collections import Counter

DATA = pathlib.Path(__file__).parent / "data"

# What the user picks in the "company" box -> how records are selected for it.
SUBJECTS = {
    "Weave": {
        "label": "Weave (the company Groundline reports for)",
        "title": "Weave brand brief",
        "min_relevance": 1,
        "focus": "Weave's reputation, brand perception, risks and what the brand team should do next. "
                 "Compare with competitors where the evidence allows.",
    },
    "Podium": {"label": "Podium (competitor)", "title": "Competitor watch: Podium", "min_relevance": 2,
               "focus": "What Podium is doing, how it is perceived, and what it means for Weave (threats and openings)."},
    "Birdeye": {"label": "Birdeye (competitor)", "title": "Competitor watch: Birdeye", "min_relevance": 2,
                "focus": "What Birdeye is doing, how it is perceived, and what it means for Weave (threats and openings)."},
    "NexHealth": {"label": "NexHealth (competitor)", "title": "Competitor watch: NexHealth", "min_relevance": 2,
                  "focus": "What NexHealth is doing, how it is perceived, and what it means for Weave (threats and openings)."},
    "Market": {"label": "The wider market (AI for customer communication)", "title": "Market landscape: AI at the front desk",
               "min_relevance": 2,
               "focus": "Trends in AI agents and customer communication that change the market Weave competes in, "
                        "and what Weave should watch."},
}
COMPETITORS = ["Podium", "Birdeye", "NexHealth", "Solutionreach", "RevenueWell", "Lighthouse 360"]

# Plain-English source groups shown to the user -> the feeds behind them.
SOURCE_GROUPS = {
    "News and press": lambda r: r["source_type"] == "news_rss" and r["collected_via"] != "reddit_practice_owners",
    "Customer posts (Reddit)": lambda r: r["collected_via"] == "reddit_practice_owners",
    "Research papers (arXiv)": lambda r: r["source_type"] == "research_api",
    "Developer discussion (Hacker News)": lambda r: r["collected_via"].startswith("hn_"),
}

MIN_ARTICLES = 3   # A4 rule: no brief from fewer than 3 items
LVL = {"none": 0, "low": 1, "medium": 2, "high": 3}


class UserError(Exception):
    """A problem the user can fix. The message is shown as-is, so write it in plain English."""


def load_records():
    return json.loads((DATA / "records.json").read_text(encoding="utf-8"))


def load_manifests():
    return json.loads((DATA / "manifests.json").read_text(encoding="utf-8"))


def parse_date(s):
    return dt.date.fromisoformat(s)


def data_window(records):
    dates = sorted(r["published_date"] for r in records)
    return parse_date(dates[0]), parse_date(dates[-1])


def source_group(r):
    return next((g for g, test in SOURCE_GROUPS.items() if test(r)), "News and press")


def select(records, subject, start, end, groups):
    """Records that feed one brief. Raises UserError when the request can't make a fair brief."""
    if subject not in SUBJECTS:
        raise UserError("Please choose a company from the list.")
    if not start or not end:
        raise UserError("Please pick both a start date and an end date. Click the date box once for the start, then again for the end.")
    if start > end:
        raise UserError("The start date is after the end date. Swap them and try again.")
    if not groups:
        raise UserError("Choose at least one kind of source. Most briefs need 'News and press'.")
    s = SUBJECTS[subject]
    return [r for r in records
            if r["entity"] == subject and (r["relevance"] or 0) >= s["min_relevance"]
            and start <= parse_date(r["published_date"]) <= end
            and source_group(r) in groups]


def check_enough(recs, subject, start, end, total=None):
    if len(recs) >= MIN_ARTICLES:
        return
    if total is not None and total < MIN_ARTICLES:
        raise UserError(f"Groundline has found only {total} {subject} article{'s' if total != 1 else ''} in all the data it has collected. "
                        f"It needs at least {MIN_ARTICLES} to write a fair brief, so it won't stretch thin evidence. "
                        "Pick a different company, or check back after the next weekly collection.")
    span = f"{start:%b %d} and {end:%b %d, %Y}"
    if not recs:
        raise UserError(f"No {subject} articles were found between {span}. "
                        "Try a wider date range, or turn on more kinds of sources.")
    raise UserError(f"Only {len(recs)} {subject} article{'s' if len(recs) > 1 else ''} found between {span}. "
                    f"Groundline needs at least {MIN_ARTICLES} to write a fair brief, so it won't stretch thin evidence. "
                    "Try a wider date range, or pick a different company.")


def tone_words(x):
    if x is None:
        return "n/a"
    if x >= 0.75:
        return "positive"
    if x >= 0.25:
        return "slightly positive"
    if x > -0.25:
        return "neutral"
    if x > -0.75:
        return "slightly negative"
    return "negative"


def stats_for(recs):
    dates = sorted(r["published_date"] for r in recs)
    sent = [r["sentiment"] or 0 for r in recs]
    return {
        "records": len(recs),
        "sources": len({r["source_name"] for r in recs}),
        "date_range": f"{dates[0]} to {dates[-1]}" if dates else "n/a",
        "avg_sentiment": round(sum(sent) / len(sent), 2) if sent else 0,
        "positive": sum(s > 0 for s in sent),
        "neutral": sum(s == 0 for s in sent),
        "negative": sum(s < 0 for s in sent),
        "themes": dict(Counter(r["theme"] for r in recs if r["theme"]).most_common(6)),
        "evidence": dict(Counter(r["evidence"] for r in recs if r["evidence"])),
        "risks_high_or_medium": sum(LVL.get(r["risk_to_weave"], 0) >= 2 for r in recs),
        "opportunities_high_or_medium": sum(LVL.get(r["opportunity_for_weave"], 0) >= 2 for r in recs),
    }


def _score(r, today):
    recent = 1 if (today - parse_date(r["published_date"])).days <= 21 else 0
    pts = float(r["engagement_points"] or 0)
    return ((r["relevance"] or 0) * 2 + abs(r["sentiment"] or 0) + LVL.get(r["risk_to_weave"], 0) * 1.5
            + LVL.get(r["opportunity_for_weave"], 0) * 1.2 + recent + min(2, pts / 200))


def evidence_pack(recs, n, today):
    """The n records most worth reading, ranked the same way every time."""
    ranked = sorted(recs, key=lambda r: (-_score(r, today), r["record_id"]))[:n]
    return [{
        "id": r["record_id"], "date": r["published_date"], "source": r["source_name"], "title": r["title"],
        "key_fact": r["key_fact"], "entity": r["entity"], "sentiment": r["sentiment"], "theme": r["theme"],
        "evidence": r["evidence"], "risk": r["risk_to_weave"], "opportunity": r["opportunity_for_weave"],
        "why": r["why"], "url": r["discussion_url"] or r["url"],
    } for r in ranked]


def build_request(records, subject, start, end, groups):
    """Everything the writer needs: stats, evidence and the brief's framing."""
    recs = select(records, subject, start, end, groups)
    if len(recs) < MIN_ARTICLES:
        first, last = data_window(records)
        check_enough(recs, subject, start, end, total=len(select(records, subject, first, last, list(SOURCE_GROUPS))))
    evidence = evidence_pack(recs, 25, end)
    if subject == "Weave":
        rivals = [r for r in records if r["entity"] in COMPETITORS and (r["relevance"] or 0) >= 2
                  and start <= parse_date(r["published_date"]) <= end and source_group(r) in groups]
        have = {e["id"] for e in evidence}
        evidence += [e for e in evidence_pack(rivals, 8, end) if e["id"] not in have]
    return {"subject": subject, **SUBJECTS[subject], "stats": stats_for(recs), "evidence": evidence,
            "start": start.isoformat(), "end": end.isoformat(), "groups": sorted(groups)}


def request_key(req):
    return f'{req["subject"]}|{req["start"]}|{req["end"]}|{",".join(req["groups"])}'


def rules_brief(req):
    """Used only when no AI model answers: lists the top items, no interpretation."""
    ev, st = req["evidence"], req["stats"]
    claim = lambda e: {"text": f'{e["title"]} ({e["source"]}, {e["date"]}).', "cite": [e["id"]], "verdict": "supported"}
    neg = [e for e in ev if (e["sentiment"] or 0) < 0 or e["risk"] not in (None, "none")][:3]
    pos = [e for e in ev if (e["sentiment"] or 0) > 0][:3]
    sections = [{"title": "Highest-priority items", "claims": [claim(e) for e in ev[:4]]},
                {"title": "Negative or risky coverage", "claims": [claim(e) for e in neg]},
                {"title": "Positive coverage", "claims": [claim(e) for e in pos]}]
    return {
        "headline": f'{req["subject"]}: {st["records"]} articles tracked, overall tone {tone_words(st["avg_sentiment"])}',
        "summary": "The AI writer was unavailable, so this brief lists the most important source articles "
                   f'without interpretation. {st["records"]} articles from {st["sources"]} sources, {st["date_range"]}.',
        "sections": [s for s in sections if s["claims"]],
        "archetype_read": None,
        "actions": [{"action": "Read the items above and try again in a few minutes for the full AI brief.",
                     "why": "The AI models were busy or unreachable.", "cite": [ev[0]["id"]], "verdict": "supported"}],
    }
