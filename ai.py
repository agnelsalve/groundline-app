"""Groundline AI roles: writer, fact-checker and single-article analyst.

Ported from the A4 workflow (ai_client.js, 23_brief_writer.js, 24_fact_checker.js,
analyst_core.js). Calls Gemini through its OpenAI-compatible endpoint. Each role has
its own model chain; when a model is busy or out of quota the next one is tried, and
the fact-checker never uses the model that wrote the brief.
"""
import json
import os
import re
import time

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
CHAINS = {
    "writer": ["gemini-3.8-flash", "gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
    "checker": ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"],
    "analyst": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.5-flash"],
}


class AIUnavailable(Exception):
    """Every model in the chain failed. The message is safe to show the user."""


def api_key():
    try:
        import streamlit as st
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    key = key or os.environ.get("GEMINI_API_KEY", "")
    return key if key and not key.startswith("your_") else ""


def _parse(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None


def complete(role, system, user, validate=None, avoid=None, max_tokens=8000, temperature=0.2, deadline_s=90, request_timeout=60, on_try=None):
    """Return (data, model). Tries each model in the role's chain until one gives valid JSON."""
    key = api_key()
    if not key:
        raise AIUnavailable("No AI key is set up for this app.")
    chain = [m for m in CHAINS[role] if m != avoid] or CHAINS[role]
    started, problems = time.time(), []
    for model in chain:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        extra = {"response_format": {"type": "json_object"}}
        for attempt in range(3):
            left = deadline_s - (time.time() - started)
            if left < 10:
                raise AIUnavailable("The AI took too long to answer.")
            if on_try:
                on_try(model)
            try:
                r = requests.post(BASE, headers={"Authorization": f"Bearer {key}"}, timeout=min(request_timeout, left),
                                  json={"model": model, "messages": messages, "temperature": temperature,
                                        "max_completion_tokens": max_tokens, **extra})
            except requests.RequestException as e:
                problems.append(f"{model}: network {type(e).__name__}")
                break
            if r.status_code == 400 and extra:
                extra = {}           # model rejects JSON mode: ask again without it
                continue
            if r.status_code in (429, 401, 403, 404):
                problems.append(f"{model}: {r.status_code}")
                break                # out of quota or not available: next model
            if r.status_code >= 500:
                problems.append(f"{model}: {r.status_code}")
                break                # busy: the next model is usually faster than waiting
            try:
                content = r.json()["choices"][0]["message"].get("content") or ""
                data = _parse(content)
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                content, data = "", None
            problem = "reply was not valid JSON" if data is None else (validate(data) if validate else None)
            if not problem:
                return data, model
            problems.append(f"{model}: {problem}")
            if attempt == 2:
                break
            # Show the model its own mistake once, as A4 did.
            messages += [{"role": "assistant", "content": content},
                         {"role": "user", "content": f"Your reply had a problem: {problem}. Return corrected JSON only."}]
    raise AIUnavailable("All AI models were busy or out of quota (" + "; ".join(problems[-4:]) + ").")


# ── Writer ───────────────────────────────────────────────────────────────────
WRITER_SYSTEM = """You write weekly brand-intelligence briefs for the brand and data team at Weave Communications.
Write for a busy marketing lead: plain English, specific, no hype, no filler.

HARD RULES
1. Use ONLY facts found in EVIDENCE. Never add outside knowledge, names, numbers or dates.
2. Every claim must cite at least one evidence id in "cite" (e.g. ["GL-1a2b3c4d"]). Only cite ids that appear in EVIDENCE.
3. Numbers (counts, averages, shares) may come ONLY from STATS - copy them exactly.
4. If the evidence is thin, say so plainly instead of stretching it.
5. Describe how the brand is perceived in the sources' own words. Do not use brand-archetype labels (Ruler, Hero, Creator, ...).

Return JSON:
{"headline": "<=14 words, the single most important takeaway",
 "summary": "2-3 sentences for someone who reads nothing else",
 "sections": [{"title": "What happened", "claims": [{"text": "...", "cite": ["GL-..."]}]},
              {"title": "How the brand is perceived", "claims": [...]},
              {"title": "Risks to watch", "claims": [...]},
              {"title": "Openings for Weave", "claims": [...]}],
 "actions": [{"action": "a concrete next step for the Weave team", "why": "one sentence", "cite": ["GL-..."]}]}
Use 2-4 claims per section (fewer if evidence is thin) and exactly 3 actions."""


def _validate_brief(ids):
    known = set(ids)

    def check(b):
        if not isinstance(b, dict) or not isinstance(b.get("headline"), str) or not isinstance(b.get("summary"), str):
            return "missing headline or summary"
        if not isinstance(b.get("sections"), list) or len(b["sections"]) < 2:
            return "need at least 2 sections"
        claims = [c for s in b["sections"] for c in (s.get("claims") or [])] + list(b.get("actions") or [])
        if len(claims) < 4:
            return "too few claims"
        for c in claims:
            if not isinstance(c.get("cite"), list) or not c["cite"]:
                return f'every claim needs a "cite" array - missing on: "{str(c.get("text") or c.get("action"))[:60]}"'
        cited = [i for c in claims for i in c["cite"]]
        if cited and sum(i in known for i in cited) / len(cited) < 0.5:
            return "most cited ids are not in EVIDENCE - cite only the given ids"
        if not b.get("actions"):
            return "missing actions"
        return None
    return check


def write_brief(req, on_try=None):
    evidence = [{k: v for k, v in e.items() if k != "url"} for e in req["evidence"]]
    user = (f'BRIEF: {req["title"]}\nFOCUS: {req["focus"]}\nPERIOD: {req["stats"]["date_range"]}\n\n'
            f'STATS:\n{json.dumps(req["stats"], indent=1)}\n\nEVIDENCE:\n{json.dumps(evidence, ensure_ascii=False)}')
    return complete("writer", WRITER_SYSTEM, user, validate=_validate_brief([e["id"] for e in evidence]),
                    max_tokens=12000, temperature=0.3, deadline_s=100, request_timeout=70, on_try=on_try)


# ── Fact-checker ─────────────────────────────────────────────────────────────
CHECKER_SYSTEM = """You are a strict, independent fact-checker. You did NOT write these claims.
For each claim you get the claim text and the source records it cites (title + key fact + source + date), plus STATS: the counts code computed from every record.
Rule on what the cited records say - not on what is true in the world:
- "supported": the cited records clearly state or directly imply the claim
- "partial": some of the claim is supported, but part is overstated, generalized, or adds detail not in the records
- "unsupported": the cited records do not back the claim
Recommendations ("Weave should...") are "supported" when the situation they respond to is supported.
Counts, averages and shares that match STATS are "supported": code computed STATS from all the records, so they need no article.
Return JSON: {"checks":[{"n": <claim number>, "verdict": "supported|partial|unsupported", "reason": "<=20 words"}]}"""
VERDICTS = ("supported", "partial", "unsupported")


def _claims_of(b):
    out = []
    for si, s in enumerate(b.get("sections") or []):
        for ci, c in enumerate(s.get("claims") or []):
            out.append({"where": f"s{si}.{ci}", "section": s.get("title", ""), "text": c.get("text", ""), "cite": c.get("cite") or []})
    ar = b.get("archetype_read")
    if ar and ar.get("text"):
        out.append({"where": "archetype", "section": "Archetype read", "text": ar["text"], "cite": ar.get("cite") or []})
    for ai, a in enumerate(b.get("actions") or []):
        out.append({"where": f"a{ai}", "section": "Actions", "text": f'{a.get("action", "")} - {a.get("why", "")}', "cite": a.get("cite") or []})
    return out


def fact_check(brief, req, writer_model, on_try=None):
    """Returns (published_brief, fact_check). Unsupported claims are removed and kept in the log."""
    ev = {e["id"]: e for e in req["evidence"]}
    claims = _claims_of(brief)
    for c in claims:
        c["fabricated_cites"] = [i for i in c["cite"] if i not in ev]
        if not any(i in ev for i in c["cite"]):
            c.update(verdict="unsupported", reason="cites no article from the evidence (made-up or missing citation)", checked_by="rule")
    todo = [c for c in claims if "verdict" not in c]
    checker, check_error = "none", None
    if todo:
        payload = [{"n": n, "claim": c["text"], "cited": [
            {k: ev[i][k] for k in ("id", "title", "key_fact", "source", "date")} for i in c["cite"] if i in ev]}
            for n, c in enumerate(todo)]
        need = -(-len(todo) * 8 // 10)

        def ok(d):
            if not isinstance(d, dict) or not isinstance(d.get("checks"), list):
                return 'missing "checks" array'
            if sum(isinstance(x, dict) and x.get("verdict") in VERDICTS for x in d["checks"]) < need:
                return "a verdict is needed for every claim"
            return None
        try:
            data, checker = complete("checker", CHECKER_SYSTEM, json.dumps({"STATS": req["stats"], "claims": payload}, ensure_ascii=False),
                                     validate=ok, avoid=writer_model, max_tokens=2000 + 150 * len(todo),
                                     temperature=0, deadline_s=70, request_timeout=50, on_try=on_try)
            for x in data["checks"]:
                try:
                    c = todo[int(x.get("n"))]
                except (TypeError, ValueError, IndexError):
                    continue
                if x.get("verdict") in VERDICTS:
                    c.update(verdict=x["verdict"], reason=str(x.get("reason", ""))[:200], checked_by=checker)
        except AIUnavailable as e:
            check_error = str(e)
    for c in claims:
        if "verdict" not in c:
            c.update(verdict="unverified", reason="fact-checker unavailable", checked_by="none")

    checked = [c for c in claims if c["verdict"] != "unverified"]
    sup = sum(c["verdict"] == "supported" for c in checked)
    part = sum(c["verdict"] == "partial" for c in checked)
    score = round((sup + 0.5 * part) / len(checked), 3) if checked else None
    status = "unverified" if score is None else "verified" if score >= 0.85 else "needs_review" if score >= 0.6 else "failed"

    verdict = {c["where"]: c["verdict"] for c in claims}
    keep = {w for w, v in verdict.items() if v != "unsupported"}
    published = dict(brief)
    published["sections"] = [
        {**s, "claims": [{**c, "verdict": verdict[f"s{si}.{ci}"]} for ci, c in enumerate(s.get("claims") or []) if f"s{si}.{ci}" in keep]}
        for si, s in enumerate(brief.get("sections") or [])]
    published["sections"] = [s for s in published["sections"] if s["claims"]]
    ar = brief.get("archetype_read")
    published["archetype_read"] = {**ar, "verdict": verdict["archetype"]} if ar and "archetype" in keep else None
    published["actions"] = [{**a, "verdict": verdict[f"a{ai}"]} for ai, a in enumerate(brief.get("actions") or []) if f"a{ai}" in keep]
    return published, {
        "checker": checker, "check_error": check_error, "status": status, "groundedness": score,
        "claims_total": len(claims), "supported": sup, "partial": part,
        "unsupported": sum(c["verdict"] == "unsupported" for c in claims),
        "unverified": len(claims) - len(checked),
        "fabricated_citations": sum(len(c["fabricated_cites"]) for c in claims), "log": claims,
    }


# ── Single-article analyst ───────────────────────────────────────────────────
ENTITIES = ["Weave", "Podium", "Birdeye", "NexHealth", "Solutionreach", "RevenueWell", "Lighthouse 360", "Market", "None"]
THEMES = ["product", "ai_strategy", "pricing", "customer_experience", "partnership", "m_and_a", "financials",
          "legal_regulatory", "leadership", "market_trend", "other"]
LEVELS = ["none", "low", "medium", "high"]
ARCHETYPES = ["Innocent", "Everyman", "Hero", "Outlaw", "Explorer", "Creator", "Ruler", "Magician", "Lover", "Caregiver", "Jester", "Sage"]

ANALYST_SYSTEM = f"""You are the brand-intelligence analyst for Weave Communications (NYSE: WEAV), a customer-communication and payments platform for ~40,000 dental, optometry and veterinary practices. Direct competitors: Podium, Birdeye, NexHealth, Solutionreach, RevenueWell, Lighthouse 360.

You receive one news item, paper or community post. Judge it ONLY from its title and summary. Never invent facts.

Return JSON: {{"items":[{{...}}]}} with one object and exactly these fields:
- "id": the input id, unchanged
- "relevance": 0 = unrelated to Weave's market (e.g. a sports "podium", a fabric "weave"), 1 = general AI/tech background, 2 = adjacent market (AI agents for customer service, SMB software, healthcare practices), 3 = directly about Weave or a named competitor
- "entity": one of {json.dumps(ENTITIES)}. "Market" for industry items, "None" when relevance is 0
- "sentiment": integer -2..2, the tone toward that entity (0 if neutral or relevance 0)
- "theme": one of {json.dumps(THEMES)}
- "evidence": "announced" (company says it), "proven" (research/data), "reported" (journalism), "discussed" (opinion/community)
- "risk_to_weave": one of {json.dumps(LEVELS)}. high = could hurt Weave's reputation, revenue or stock soon (lawsuit, outage, downgrade, a competitor winning Weave's customers)
- "opportunity_for_weave": one of {json.dumps(LEVELS)}. high = a competitor stumbling or a market shift Weave can act on now
- "archetype": which of {json.dumps(ARCHETYPES)} this coverage portrays the entity as, or null if it doesn't portray a brand
- "key_fact": ONE sentence stating the main fact, using only information in the title/summary
- "why": at most 20 words explaining the risk/opportunity rating"""


def _validate_item(d):
    items = d.get("items") if isinstance(d, dict) else None
    if not items or not isinstance(items[0], dict):
        return 'missing "items" array'
    it = items[0]
    try:
        it["relevance"] = max(0, min(3, round(float(it["relevance"]))))
        it["sentiment"] = max(-2, min(2, round(float(it["sentiment"]))))
    except (KeyError, TypeError, ValueError):
        return "relevance and sentiment must be numbers"
    if it.get("entity") not in ENTITIES:
        return f'entity must be one of {", ".join(ENTITIES)}'
    if it.get("risk_to_weave") not in LEVELS or it.get("opportunity_for_weave") not in LEVELS:
        return "risk_to_weave/opportunity_for_weave must be none|low|medium|high"
    if it.get("theme") not in THEMES:
        it["theme"] = "other"
    if it.get("archetype") not in ARCHETYPES:
        it["archetype"] = None
    if not isinstance(it.get("key_fact"), str) or len(it["key_fact"]) < 8:
        return "key_fact must be a sentence"
    return None


def analyze_item(title, summary, on_try=None):
    user = json.dumps([{"id": "item-1", "title": title, "summary": summary}], ensure_ascii=False)
    data, model = complete("analyst", ANALYST_SYSTEM, user, validate=_validate_item, max_tokens=2000, temperature=0, deadline_s=45, request_timeout=25, on_try=on_try)
    return data["items"][0], model
