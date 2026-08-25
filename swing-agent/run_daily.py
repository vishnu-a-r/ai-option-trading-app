"""Daily entry point.

SCOPE: signal generation and alerting only.

Since 1 April 2026 SEBI's retail algo framework is fully in force - any order
placed by an algorithm needs an exchange-issued Algo-ID, must route through the
broker's registered infrastructure, and requires static IP whitelisting.
Self-written API strategies are covered, not exempt.

There is deliberately no execution module in this project. Do not add order
placement, auto square-off, or programmatic stop-loss submission. Orders are
placed manually or via broker GTT/bracket orders.
"""
from __future__ import annotations


def main() -> None:
    # 1. load config, validate scoring weights sum to 1.0
    # 2. resolve universe (Nifty 500 + F&O list), apply exclusions
    # 3. fetch prices, fundamentals, institutional, futures  [cached]
    # 4. market regime from aggregate FII/DII flow + index structure
    # 5. long screen over full universe; short screen over F&O only
    # 6. fundamental gate / deterioration flags
    # 7. composite rank
    # 8. stops, sizing, portfolio gates
    # 9. write JSON + summary, notify
    raise NotImplementedError


if __name__ == "__main__":
    main()
