from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from support.firewall import check

if TYPE_CHECKING:
    from forbql import Firewall

QUERIES = [
    "SELECT count(*) FROM accounts",
    "SELECT status, count(*) AS n, sum(balance) AS total FROM accounts GROUP BY status",
    "SELECT status, avg(balance), min(balance), max(balance) FROM accounts GROUP BY 1 ORDER BY 2 DESC",
    "SELECT a.id, t.amount FROM accounts a JOIN transactions t ON t.account_id = a.id WHERE t.amount > 100",
    "SELECT c.region, count(DISTINCT a.id) FROM clients c LEFT JOIN accounts a ON a.client_id = c.id GROUP BY c.region",
    "SELECT id FROM accounts WHERE status IN ('open', 'frozen') AND balance BETWEEN 10 AND 20",
    "SELECT id FROM accounts WHERE status IS NOT NULL AND NOT (balance < 0)",
    "SELECT id FROM accounts a WHERE balance > (SELECT avg(balance) FROM accounts)",
    "SELECT id FROM accounts WHERE client_id = ANY (SELECT id FROM clients)",
    "WITH big AS (SELECT id, balance FROM accounts WHERE balance > 1000) SELECT count(*) FROM big",
    "SELECT id, CASE WHEN balance > 0 THEN 'credit' ELSE 'debit' END AS side FROM accounts",
    "SELECT id, coalesce(status, 'none'), nullif(status, ''), upper(status), lower(status) FROM accounts",
    "SELECT id, round(balance, 2), abs(balance), floor(balance), ceil(balance) FROM accounts",
    "SELECT id, length(full_name), substring(full_name, 1, 3), trim(full_name) FROM clients",
    "SELECT id, replace(full_name, ' ', '_'), concat(full_name, '!') FROM clients",
    "SELECT id, row_number() OVER (ORDER BY balance DESC) AS place FROM accounts",
    "SELECT id, rank() OVER (PARTITION BY status ORDER BY balance), lag(balance) OVER (ORDER BY id) FROM accounts",
    "SELECT id, CAST(balance AS INT), CAST(id AS TEXT) FROM accounts",
    "SELECT DISTINCT status FROM accounts ORDER BY status LIMIT 10 OFFSET 5",
    "SELECT id FROM accounts EXCEPT SELECT account_id FROM transactions",
    "SELECT id, greatest(balance, 0), least(balance, 0) FROM accounts",
    "SELECT full_name AS name FROM clients WHERE full_name LIKE 'A%' ORDER BY name",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_everyday_queries_pass_on_every_engine(firewall: Firewall, sql: str):
    verdict = check(firewall, sql)

    assert verdict.allowed, verdict.violations
