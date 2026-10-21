"""Groundline: the weekly brand brief where every sentence is traced to its source.

Run locally:  streamlit run app.py
"""
import datetime as dt
import logging
import re

import streamlit as st

import ai
import core
import pipeline

st.set_page_config(page_title="Groundline", page_icon="🧭", layout="centered")
log = logging.getLogger("groundline")

VERDICT_MARK = {"supported": ":green[✓]", "partial": ":orange[◐ partly supported]", "unverified": ":gray[· not checked]"}
STATUS = {
    "verified": ("success", "✅ **Verified.** The fact-checker found that {pct} of this brief is backed by the articles it cites."),
    "needs_review": ("warning", "⚠️ **Needs a human look.** Only {pct} of this brief is backed by its sources (the bar is 85%). Read the flagged lines before sharing."),
    "failed": ("error", "❌ **Not safe to share.** Only {pct} of this brief is backed by its sources. Use it as a reading list, not a report."),
    "unverified": ("warning", "⚠️ **Not fact-checked.** The checker was unavailable, so no trust score could be given."),
    "ai_offline": ("info", "ℹ️ **AI unavailable, showing source list.** These lines are the articles' own headlines, so nothing needed checking."),
}


def md(text):
    """Escape characters Streamlit would read as formatting ($650M would turn into maths)."""
    return re.sub(r"([$*_`~])", r"\\\1", str(text or ""))


@st.cache_data
def records():
    return core.load_records()


@st.cache_data
def manifests():
    return core.load_manifests()


@st.cache_data
def saved_briefs():
    return pipeline.load_saved()


@st.cache_resource
def fresh_briefs():
    return {}


def get_result(req, use_ai, progress=lambda msg: None):
    """Reuse a fresh brief already written for the same request, so the AI isn't asked twice."""
    key, made = core.request_key(req), fresh_briefs()
    if use_ai and key in made:
        return made[key]
    result = pipeline.generate(req, use_ai=use_ai, saved=saved_briefs(), progress=progress)
    if result["mode"] == "live":
        made[key] = result
    return result


# ── Rendering ────────────────────────────────────────────────────────────────
def render_brief(result):
    req, brief, fc = result["request"], result["brief"], result["fact_check"]
    st_ = req["stats"]
    ev = {e["id"]: e for e in req["evidence"]}

    # Number sources in the order the brief first cites them.
    order = []
    claims_seen = [c for s in brief.get("sections", []) for c in s["claims"]] + list(brief.get("actions", []))
    if brief.get("archetype_read"):
        claims_seen.append(brief["archetype_read"])
    for c in claims_seen:
        for i in c.get("cite", []):
            if i in ev and i not in order:
                order.append(i)
    num = {i: n + 1 for n, i in enumerate(order)}

    def cites(c):
        return " ".join(f"[[{num[i]}]]({ev[i]['url']})" for i in c.get("cite", []) if i in num)

    def mark(c):
        return " " + VERDICT_MARK.get(c.get("verdict"), "") if result["mode"] != "rules" else ""

    if result["mode"] == "saved":
        when = result.get("created_at", "")[:10]
        why = ("The AI is busy right now, so you're seeing" if result.get("note") else "This is")
        st.info(f"🗂️ **Showing the saved brief from {when}.** {why} the last brief Groundline wrote and fact-checked "
                "for these exact settings. Turn on *Write a fresh brief with AI* for a new one.")
    elif result["mode"] == "rules":
        why = ("The AI writer is busy right now and" if result.get("note") else "AI writing is turned off and")
        st.info(f"{why} there's no saved brief for these settings, so here are the most important articles. "
                "Try again with *Write a fresh brief with AI* turned on, or use the default dates.")

    kind, msg = STATUS.get(fc["status"], STATUS["unverified"])
    pct = f"{fc['groundedness']:.0%}" if fc.get("groundedness") is not None else "n/a"
    getattr(st, kind)(msg.format(pct=pct))

    c1, c2, c3 = st.columns(3)
    c1.metric("Trust score", pct, help="Share of the brief's sentences the independent fact-checker found in the cited articles. "
                                       "Partly supported sentences count as half. 85% or more earns the Verified badge.")
    c2.metric("Articles read", st_["records"], help="Articles about this company in your date range, after junk was filtered out.")
    c3.metric("Outlets", st_["sources"], help="Number of different publishers or sites.")
    st.markdown(f"**Overall tone of the coverage: {core.tone_words(st_['avg_sentiment'])}** · "
                f"{st_['positive']} positive, {st_['neutral']} neutral, {st_['negative']} negative articles")

    st.subheader(md(brief.get("headline", "")))
    st.write(md(brief.get("summary", "")))

    for s in brief.get("sections", []):
        st.markdown(f"#### {md(s['title'])}")
        st.markdown("\n".join(f"- {md(c['text'])} {cites(c)}{mark(c)}" for c in s["claims"]))

    ar = brief.get("archetype_read")
    if ar:
        st.markdown("#### Brand personality in the coverage")
        st.markdown(f"{md(ar['text'])} {cites(ar)}{mark(ar)}")

    if brief.get("actions"):
        st.markdown("#### What to do next")
        for n, a in enumerate(brief["actions"], 1):
            st.markdown(f"**{n}. {md(a['action'])}**  \n{md(a.get('why', ''))} {cites(a)}{mark(a)}")

    st.markdown("#### Sources")
    st.caption("Each number in the brief links to the article it came from.")
    st.markdown("\n".join(f"{num[i]}. [{md(ev[i]['title'])}]({ev[i]['url']}) — {md(ev[i]['source'])}, {ev[i]['date']}" for i in order))

    removed = [c for c in fc.get("log", []) if c["verdict"] == "unsupported"]
    partial = [c for c in fc.get("log", []) if c["verdict"] == "partial"]
    if fc.get("log"):
        with st.expander(f"Fact-check log: {len(removed)} sentence{'s' if len(removed) != 1 else ''} removed, {len(partial)} partly supported"):
            st.caption(f"Written by **{result['written_by']}**, checked by **{fc.get('checker', 'none')}**: two different AI models, "
                       "so no model grades its own work.")
            if removed:
                st.markdown("**Removed before you saw the brief** (the cited articles don't say this):")
                st.markdown("\n".join(f"- ~~{md(c['text'])}~~  \n  :gray[{md(c.get('reason', ''))}]" for c in removed))
            if partial:
                st.markdown("**Kept, but flagged as partly supported:**")
                st.markdown("\n".join(f"- {md(c['text'])}  \n  :gray[{md(c.get('reason', ''))}]" for c in partial))
            if not removed and not partial:
                st.markdown("Every sentence was fully supported by its sources.")

    with st.expander("How the numbers were calculated"):
        th = ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in st_["themes"].items()) or "none"
        st.markdown(
            f"- **Period:** {st_['date_range']}\n"
            f"- **Tone:** {st_['positive']} positive, {st_['neutral']} neutral, {st_['negative']} negative "
            f"(average {st_['avg_sentiment']:+.2f} on a scale from −2 to +2)\n"
            f"- **Main topics:** {th}\n"
            f"- **Risks rated medium or high:** {st_['risks_high_or_medium']}; **openings rated medium or high:** {st_['opportunities_high_or_medium']}\n\n"
            "Every number here is counted by code from the source data before the AI starts writing, so the AI cannot make up a statistic.")

    st.download_button("⬇️ Download this brief", to_markdown(result, order, num), width="stretch",
                       file_name=f"groundline_{req['subject'].lower()}_{req['end']}.md", mime="text/markdown")


def to_markdown(result, order, num):
    req, brief, fc = result["request"], result["brief"], result["fact_check"]
    ev = {e["id"]: e for e in req["evidence"]}
    ref = lambda c: "".join(f" [{num[i]}]" for i in c.get("cite", []) if i in num)
    g = fc.get("groundedness")
    out = [f"# {brief.get('headline', '')}", f"*{req['title']} · {req['start']} to {req['end']} · Trust score "
           f"{f'{g:.0%}' if g is not None else 'n/a'}*", "", brief.get("summary", ""), ""]
    for s in brief.get("sections", []):
        out += [f"## {s['title']}"] + [f"- {c['text']}{ref(c)}" for c in s["claims"]] + [""]
    if brief.get("archetype_read"):
        out += ["## Brand personality in the coverage", brief["archetype_read"]["text"] + ref(brief["archetype_read"]), ""]
    if brief.get("actions"):
        out += ["## What to do next"] + [f"{n}. **{a['action']}** {a.get('why', '')}{ref(a)}" for n, a in enumerate(brief["actions"], 1)] + [""]
    out += ["## Sources"] + [f"{num[i]}. {ev[i]['title']} ({ev[i]['source']}, {ev[i]['date']}) {ev[i]['url']}" for i in order]
    return "\n".join(out)


def render_thin(recs):
    if not recs:
        return
    with st.expander(f"See the {len(recs)} article{'s' if len(recs) > 1 else ''} that were found"):
        st.markdown("\n".join(f"- [{md(r['title'])}]({r['discussion_url'] or r['url']}) — {md(r['source_name'])}, {r['published_date']}"
                              for r in sorted(recs, key=lambda r: r["published_date"], reverse=True)))


# ── Tabs ─────────────────────────────────────────────────────────────────────
def brief_tab():
    recs = records()
    first, last = core.data_window(recs)
    default_start = last - dt.timedelta(days=90)
    counts = {s: len(core.select(recs, s, first, last, list(core.SOURCE_GROUPS))) for s in core.SUBJECTS}

    with st.form("brief"):
        subject = st.selectbox("1. Who should the brief be about?", list(core.SUBJECTS),
                               format_func=lambda s: f"{core.SUBJECTS[s]['label']} · {counts[s]} articles",
                               help="Weave is the company this tool reports for. Pick a competitor to see what they're up to.")
        dates = st.date_input("2. Which dates?", value=(default_start, last), min_value=first, max_value=last, format="MM/DD/YYYY",
                              help=f"Articles were last collected on {last:%B %d, %Y}. Click once for the start date and once for the end date.")
        groups = st.pills("3. Which kinds of sources?", list(core.SOURCE_GROUPS), selection_mode="multi", default=list(core.SOURCE_GROUPS),
                          help="Click to turn a source on or off. News covers press, analyst and legal notices. "
                               "The others add customer, research and developer views.")
        has_key = bool(ai.api_key())
        fresh = st.toggle("Write a fresh brief with AI (usually 1–2 minutes)", value=has_key, disabled=not has_key,
                          help="Off: instantly show the last brief Groundline saved for these settings, if there is one.")
        go = st.form_submit_button("Write my brief", type="primary", width="stretch")

    if go:
        start, end = (list(dates) + [None, None])[:2] if isinstance(dates, (tuple, list)) else (dates, None)
        st.session_state.pop("result", None)
        try:
            req = core.build_request(recs, subject, start, end, groups)
        except core.UserError as e:
            st.error(f"**Can't write that brief yet.** {e}")
            if start and end and groups and start <= end:
                render_thin(core.select(recs, subject, start, end, groups))
            return
        with st.status("Writing your brief…", expanded=True) as status:
            st.write(f"📥 Gathered {req['stats']['records']} {subject} articles from {req['stats']['sources']} outlets, "
                     f"and counted the numbers with code.")
            step = st.empty()
            tried = []

            def progress(msg):
                stage, _, model = msg.partition(":")
                if model:
                    tried.append(model)
                busy = " (the first AI was busy, so trying another)" if len(tried) > 1 and model else ""
                if stage == "writing":
                    step.write(f"✍️ An AI writer is drafting the brief from those articles only{busy}…")
                else:
                    step.write("✍️ Draft written.  \n🔎 A second, different AI is checking every sentence "
                               f"against the articles it cites{busy}…")
            result = get_result(req, fresh, progress)
            done = {"live": "Brief written and fact-checked", "saved": "Showing the last saved brief",
                    "rules": "Showing the most important articles"}[result["mode"]]
            status.update(label=done, state="complete", expanded=False)
        st.session_state["result"] = result

    if "result" in st.session_state:
        render_brief(st.session_state["result"])


def headline_tab():
    st.markdown("Saw a headline and want to know whether it matters to Weave? Paste it here for a quick read on "
                "who it's about, its tone, and whether it's a risk or an opening.")
    with st.form("headline"):
        title = st.text_input("Headline", placeholder="e.g. ServiceTitan ends its integration with Podium")
        summary = st.text_area("First paragraph or summary (optional)", height=100,
                               help="Adding a sentence or two of the article makes the read more accurate.")
        go = st.form_submit_button("Check this headline", type="primary", width="stretch")
    if not go:
        return
    title, summary = title.strip(), summary.strip()
    if not title:
        st.error("**Paste a headline first.** Copy the title of a news article, review or post into the Headline box.")
        return
    if re.match(r"(https?://|www\.)", title, re.I):
        st.error("**Groundline can't open web links yet.** Copy the article's headline (and its first paragraph, "
                 "if you like) and paste the text instead of the link.")
        return
    if len(title.split()) < 4:
        st.error("**That's too short to judge.** Paste the full headline, at least 4 words, so there's enough to go on.")
        return
    if len(title) + len(summary) > 2000:
        st.error("**That's more text than Groundline needs.** Paste just the headline and the first paragraph "
                 "(under 2,000 characters in total).")
        return
    if not ai.api_key():
        st.warning("The AI checker isn't set up on this copy of the app, so headlines can't be checked right now.")
        return
    try:
        with st.spinner("Reading the headline…"):
            item, model = ai.analyze_item(title, summary)
    except ai.AIUnavailable:
        st.warning("**The AI is busy right now.** Please wait a minute and click the button again. Nothing you typed was lost.")
        return
    rel = ["Not related to Weave's market", "General tech background", "Related to Weave's market", "Directly about Weave or a competitor"][item["relevance"]]
    tone = {-2: "Very negative", -1: "Negative", 0: "Neutral", 1: "Positive", 2: "Very positive"}[item["sentiment"]]
    (st.success if item["relevance"] >= 2 else st.info)(f"**{rel}**" + (f" · about **{item['entity']}**" if item["entity"] not in ("None", "Market") else ""))
    c1, c2, c3 = st.columns(3)
    c1.metric("Tone", tone)
    c2.metric("Risk to Weave", item["risk_to_weave"].capitalize())
    c3.metric("Opening for Weave", item["opportunity_for_weave"].capitalize())
    st.markdown(f"**What it says:** {md(item['key_fact'])}")
    st.markdown(f"**Why this rating:** {md(item.get('why', ''))}")
    if item["relevance"] == 0:
        st.caption("Words like *podium* and *weave* show up in sports and fabric news too. Groundline filters those out of the brief.")
    st.caption(f"Read by {model}, using only the text you pasted.")


def data_tab():
    recs = records()
    first, last = core.data_window(recs)
    st.markdown(f"Groundline reads **{len(recs)} articles** collected on **{last:%B %d, %Y}**, published between "
                f"{first:%B %Y} and {last:%B %Y}. Before any AI sees them, each source has to pass a set of quality checks. "
                "A source that fails is left out.")
    for m in manifests():
        checks = m.get("checks", [])
        ok = sum(c.get("passed") for c in checks)
        icon = "✅" if m.get("verdict") == "pass" else "❌"
        with st.expander(f"{icon} {m['source']}: {m['records']} articles, {ok}/{len(checks)} checks passed"):
            st.write(m.get("represents", ""))
            st.markdown("\n".join(f"- {'✅' if c.get('passed') else '❌'} {c['check']}" + (f" ({c['detail']})" if c.get("detail") else "")
                                  for c in checks))


# ── Page ─────────────────────────────────────────────────────────────────────
st.title("🧭 Groundline")
st.markdown("**The weekly brand brief you can stand behind.** Groundline reads the news, customer posts and research "
            "about Weave and its competitors, then writes a short brief. **Every sentence links to the article it came from**, "
            "and a second AI checks each one. Anything it can't back up is removed before you see it.")

tab1, tab2, tab3 = st.tabs(["📝 Weekly brief", "🔎 Check a headline", "🗄️ Where the data comes from"])
try:
    with tab1:
        brief_tab()
    with tab2:
        headline_tab()
    with tab3:
        data_tab()
except Exception:
    log.exception("Unexpected error")
    st.error("**Something went wrong on our side.** Please refresh the page and try again. "
             "If it keeps happening, try different dates or another company.")
