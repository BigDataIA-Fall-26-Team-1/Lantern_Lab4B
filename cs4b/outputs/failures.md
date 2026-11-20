# Failure log

Found in the first recording run on the real panel (evidence copied to scratch/run1/).
Every fix is to the system (column descriptions, prompt rules, or data cleaning);
no question was reworded.

## Failure 1
Question: q03 "What share of Antares Strategic Credit Fund's current fair value is first lien debt?"
What went wrong: The SQL filtered `investment_type = 'First Lien Senior Secured Debt [Member]'` and answered a first-lien share of 0. investment_type is NULL in all current rows of the real panel; the lien type is written inside identifier (as "First Lien" or "1st Lien"). The model followed DESCRIPTIONS, which promised values the panel does not have.
What fixed it: A column description. DESCRIPTIONS in src/askpanel/tools.py now says investment_type and industry are NULL in this panel and that lien type and industry are in identifier (match both "First Lien" and "1st Lien").
Result after the fix: fixed. The re-recorded q03 matches lien type with identifier LIKE '%first lien%' OR '%1st lien%' and answers 0.9579 for ANTARES STRATEGIC CREDIT FUND, the share checked independently through the server.

## Failure 2
Question: q03 (same question)
What went wrong: The name filter `bdc LIKE '%Antares Strategic Credit Fund%'` also matched ANTARES STRATEGIC CREDIT FUND II LLC, so two funds were mixed in one total. The prompt's own rule ("match a name with bdc LIKE '%WORD%'") was too loose.
What fixed it: The prompt. A RULES line in agent/model.py now says to anchor the name at its start and to exclude sibling funds whose names only add a suffix such as II or IV, unless the analyst named that fund.
Result after the fix: partly fixed. The anchored match still catches ANTARES STRATEGIC CREDIT FUND II LLC, but the model now groups by bdc, so the named fund (0.9579) and the sibling (0.9719) are separate rows instead of one mixed total. It added the NOT LIKE exclusion for q01, q04 and q08, but not here. Left as a known limitation.

## Failure 3
Question: q07 "Which holdings pull the lowest of those averages down the most?" (follows q06)
What went wrong: The model declined ("the question is ambiguous about which BDC's averages or holdings to analyze"), although the history held q06's question and SQL. No SQL, no result: the follow-up failed.
What fixed it: The prompt. A RULES line in agent/model.py now says a follow-up's "those", "it" or "that" refers to the previous turn's result, that the model should reuse that SQL as a CTE or subquery, and that it must not decline a follow-up for that reason.
Result after the fix: fixed. q07 now reuses q06's query as a CTE and returns 20 holdings. Its first two attempts timed out (over 120 s each when timed separately) and the repair edge got a 0.13 s query on the third and last allowed attempt.

## Failure 4
Question: q06 "Which ten BDCs have the lowest average price across their current debt holdings?"
What went wrong: The SQL was right, but the answer was wrong: WEST BAY BDC LLC averaged 44.26. Checking its rows through the server showed 56 unfunded commitments with principal > 0 and a fair value of $0 or a small negative number (for example principal 126,000, fair value -2,000, price -1.59). Their "price" is meaningless and dragged the average down. tools/clean_panel.py dropped unfunded commitments only when the fair value was blank.
What fixed it: Data cleaning. tools/clean_panel.py also drops rows with principal > 0, fair value <= 0 and no positive cost (2,343 rows across both schedules), then python tools/build_db.py; holdings_v still meets the contract (21,944 current holdings). Known limitation: about 690 partly drawn loans (fair value close to cost, but principal includes the undrawn part) still show low prices; the panel does not say how much is drawn.
Result after the fix: fixed. WEST BAY BDC LLC is no longer among the ten lowest averages; the lowest is now VENTURE LENDING & LEASING IX at 63.14, whose zero prices are written-off loans with a positive cost, kept on purpose.
