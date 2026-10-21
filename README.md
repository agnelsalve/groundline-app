# Groundline: Streamlit interface

> **The weekly brand brief you can stand behind.** Every sentence links to the article it came from, and a second AI checks each one before you see it.

INFO 7375 Branding & AI · Assignment 6A (Path A) · Agnel Salve

This app wraps the Groundline v2 intelligence layer from A4 (an n8n workflow) in a Streamlit interface that someone without the code can use.

| Tab | What the user does | What they get |
|---|---|---|
| 📝 **Weekly brief** | Picks a company, a date range and the kinds of sources | A one-page brief: headline, summary, cited claims, a brand-archetype read, 3 next steps, a trust score, a fact-check log and a download |
| 🔎 **Check a headline** | Pastes one headline (plus an optional paragraph) | Who it's about, its tone, its risk and opening for Weave, and why |
| 🗄️ **Where the data comes from** | Nothing | The 6 sources, each with its pass/fail quality checks |

## How a brief is made

1. **Select** the verified records for the company and dates (`core.py`). Fewer than 3 articles means no brief, because the tool won't stretch thin evidence.
2. **Count** every number (tone, outlets, risks) in code before any AI runs.
3. **Write.** A Gemini writer may use only the evidence it was given and must cite a record ID for every claim (`ai.write_brief`).
4. **Check.** A *different* Gemini model rules each claim supported, partial or unsupported. Unsupported claims are removed and kept in the log. Trust score = (supported + ½ partial) / claims checked, and 85% or more earns the Verified badge (`ai.fact_check`).
5. **Fall back** (`pipeline.generate`). If every model is busy, the app shows the last saved, fact-checked brief for the same settings. If there is none, it lists the top source articles without interpretation. The app never shows a stack trace.

## Run locally

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

Put your key in `.streamlit/secrets.toml` (git-ignored):

```toml
GEMINI_API_KEY = "..."
```

Without a key, the app still works on the saved briefs.

## Deploy (Streamlit Community Cloud)

1. Push this folder to a public GitHub repo, without `.streamlit/secrets.toml`.
2. On [share.streamlit.io](https://share.streamlit.io), choose **Create app**, pick the repo, and set the main file to `app.py`.
3. Under **Advanced settings → Secrets**, paste `GEMINI_API_KEY = "..."`.

## Refresh the data

```bash
python scripts/build_data.py
```

```bash
python scripts/build_saved.py
```

`build_data.py` copies the A4 dataset, AI judgments and source manifests into `data/`. `build_saved.py` writes and fact-checks the default briefs (last 90 and last 30 days) that the app falls back on. It needs `GEMINI_API_KEY` in the environment.
