"""Part 3 (Lab 35B): the SQL-writing model, behind record/replay.

    model = make_model(P, "replay")      # cache only: no key, no cost
    model = make_model(P, "record")      # calls Gemini, then stores the reply
    out = model(request)                 # request = askpanel.nodes.build_request(...)

Record mode needs GEMINI_API_KEY. Replay never imports google.genai.
If you change prompt_from() after recording, delete outputs/cache/ and record
again: the cache key covers the request, not the prompt text built from it.
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from askpanel import econ, llm  # noqa: E402

MIN_GAP_S = 4.5      # free tier: 15 requests per minute -> one call every 4 s, plus margin
RETRIES = 4          # on 429 (rate limit) or 5xx, wait and try again

# Guidance the kit's SYSTEM prompt does not give. Part of the prompt, so it
# shapes every answer; a change here is a "prompt" fix for your failure log.
RULES = """Rules:
- holdings_v has ONE row per CURRENT holding. Use it for any question about the current portfolio.
- For prior vs current (over time), use the holdings table with period_role = 'prior' or 'current', joined to filings ON adsh.
- Never sum both schedules together: every total would double.
- BDC names are spelled exactly as the SEC data set spells them (often upper case, with CORP, INC or LLC). Match a named BDC from the START of its name: bdc LIKE 'NAME%' (or name LIKE 'NAME%' in filings), never with a leading % and not with =.
- Sibling funds share a name and add a suffix (II, IV, a letter, INCOME FUND, LLC). When the analyst names one BDC, exclude longer names that add such a suffix, e.g. bdc LIKE 'NAME%' AND bdc NOT LIKE 'NAME II%', unless the analyst named that fund. Include bdc in the output so the reader sees which fund matched.
- price is already 100 * fair_value / principal (NULL for equity); is_debt is 1 for debt. Use them; do not rebuild them.
- Rates are decimals: 0.02 means 2%.
- Return only the columns the question needs, include bdc (or name) when rows come from several BDCs, and add ORDER BY and a LIMIT (at most 50) for lists.
- Follow-ups: in a question that follows earlier ones in this conversation, "those", "them", "it" and "that" refer to the RESULT of the previous question. Reuse the previous SQL as a CTE or subquery (for example, take its lowest or highest row) and answer from there. Never decline a follow-up because it refers to earlier results.
- If the data cannot answer the question (forecasts, opinions, anything not in these columns), decline."""


def prompt_from(req):
    """The user turn Gemini sees, built only from the request (deterministic)."""
    parts = ["Tables you may query:", req["schema"], "", RULES]
    if req.get("history"):
        parts += ["", "Earlier in this conversation:"]
        for i, t in enumerate(req["history"], 1):
            parts.append(f"{i}. Question: {t['question']}\n   SQL: {t.get('sql') or '(declined)'}")
    parts += ["", f"Question: {req['question']}"]
    if req.get("error"):
        parts += ["",
                  f"Your previous attempt (attempt {req['attempt']}) failed.",
                  f"SQL: {req.get('prior_sql')}",
                  f"Error: {req['error']['code']}: {req['error']['detail']}",
                  "Fix the SQL, or decline if the data cannot answer it."]
    parts += ["", 'Reply as JSON only: {"sql": "...", "explanation": "..."} '
                  'or {"sql": null, "decline": "reason"}.']
    return "\n".join(parts)


def _parse(text):
    """Gemini's JSON reply -> sql / decline / explanation. A bad reply becomes
    neither, which the check node sends back for repair (code invalid)."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        return {"sql": None, "decline": None, "explanation": "reply was not JSON"}
    if not isinstance(d, dict):
        return {"sql": None, "decline": None, "explanation": "reply was not a JSON object"}
    return {"sql": d.get("sql") or None, "decline": d.get("decline") or None,
            "explanation": d.get("explanation") or ""}


def gemini_call(P):
    """call(req) for ReplayClient's record mode. One client, kept for the run."""
    from google import genai                      # imported only when recording
    from google.genai import errors, types

    client = genai.Client()                       # reads GEMINI_API_KEY; keep this object alive
    p_in = float(P["prices"]["usd_per_mtok_in"])
    p_out = float(P["prices"]["usd_per_mtok_out"])
    last = [0.0]

    def call(req):
        for i in range(RETRIES + 1):
            wait = MIN_GAP_S - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
            try:
                resp = client.models.generate_content(
                    model=req["model"], contents=prompt_from(req),
                    config=types.GenerateContentConfig(
                        system_instruction=req["system"], temperature=0,
                        response_mime_type="application/json"))
                break
            except errors.APIError as e:
                if getattr(e, "code", None) in (429, 500, 503) and i < RETRIES:
                    time.sleep(15 * (i + 1))      # back off: 15 s, 30 s, 45 s, ...
                    continue
                raise
        u = resp.usage_metadata
        t_in = u.prompt_token_count or 0
        t_out = (u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
        return {**_parse(resp.text), "tokens_in": t_in, "tokens_out": t_out,
                "usd": econ.step_usd(t_in, t_out, p_in, p_out),
                "raw": resp.text}                 # kept in the cache only, for the failure log

    return call


def make_model(P, mode=None, cache_dir=None):
    """A ReplayClient over Gemini. mode: 'record' or 'replay' (default params.yaml)."""
    mode = mode or P["model"]["mode"]
    if mode not in ("record", "replay"):
        raise ValueError(f"mode must be record or replay, not {mode!r}")
    cache = Path(cache_dir) if cache_dir else ROOT / P["model"]["cache_dir"]
    return llm.ReplayClient(cache, mode, call=gemini_call(P) if mode == "record" else None)