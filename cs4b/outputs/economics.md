# Unit economics: Ask the Panel

Ten questions on the real panel (72 BDC filings, 21,944 current holdings, period 2025-12-31),
recorded with gemini-3.5-flash-lite. Every number below comes from `python tools/economics.py`,
which reads outputs/questions/*.json, outputs/latency.json and params.yaml, re-runs each saved SQL
through the MCP server, and writes outputs/economics_numbers.json.

| Line | Ask the Panel |
|---|---|
| Cost per completed task | $0.00098 per answered question: $0.00881 for all 10 questions (13 model calls, 18,309 tokens, at $0.30 in and $2.50 out per million tokens), divided over the 9 answered, so the two repairs and the decline are included. $0.00088 per question asked. Actual spend $0 on the Gemini free tier. |
| Latency | Median 4.56 s from question to answer (min 1.64 s, max 16.65 s, record mode). The SQL itself takes a median 17.4 ms (max 70.9 ms, re-run through the server). Almost all the time is the model plus the 4.5 s pause between calls for the free-tier rate limit; q07's 16.65 s is three model calls and two 5 s timeouts before the repair worked. |
| Human time saved | Assumption: 20 analyst minutes per ad-hoc question at $120/hour, so $40 per question. For the 9 answered questions: x0.5 = 1.5 hours ($180), x1 = 3.0 hours ($360), x2 = 6.0 hours ($720), against $0.0088 of model cost. The analyst still spends about 2 minutes reading each answer's SQL. |
| Quality | Out of 10: 9 answered with rows, 1 declined correctly (q10), 0 failed. 2 needed a repair and were fixed within 3 attempts (q01: invalid column adsch; q07: two timeouts). 7 correct, 2 partly wrong, 0 wrong: q03 also returns the sibling fund ANTARES STRATEGIC CREDIT FUND II LLC as a second row; q07 lists holdings from all ten low-average BDCs rather than the lowest one, and its lowest prices include undrawn commitments priced at 0. All 9 saved results reproduce through the server (9/9). Judged by reading each SQL against its question and from the failure log, not by independent queries. |
| Cost of failure | Assumption: a wrong number that reaches a client note costs 4 hours of analyst and portfolio-manager time to find, correct and re-issue (4 x $120 = $480), before any reputational cost. With 2 of 10 answers partly wrong, an unreviewed answer carries about $96 of expected failure cost (0.2 x $480), against $0.00088 of model cost. Showing the SQL turns review into a 2-minute read ($4), and both partly wrong answers are visible on screen (q03 shows two funds; q07 shows rows marked Undrawn priced at 0), so a reader catches them before they reach a note. |

Reproduce: `python tools/economics.py` (no API key; needs `python tools/build_db.py` first on a clean clone).