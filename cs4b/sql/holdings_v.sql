DROP VIEW IF EXISTS holdings_v;

CREATE VIEW holdings_v AS
SELECT
    h.adsh,
    f.name AS bdc,
    f.form,
    f.period,
    h.identifier,
    h.investment_type,
    h.industry,
    h.fair_value,
    h.cost,
    h.principal,
    CASE WHEN h.principal > 0
         THEN ROUND(100.0 * h.fair_value / h.principal, 4)
    END AS price,
    h.pik_rate,
    h.interest_rate,
    h.spread,
    h.maturity,
    CASE WHEN h.principal > 0 THEN 1 ELSE 0 END AS is_debt
FROM holdings AS h
JOIN filings AS f ON f.adsh = h.adsh
WHERE h.period_role = 'current';