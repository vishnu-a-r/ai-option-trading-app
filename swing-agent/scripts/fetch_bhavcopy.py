"""Download NSE daily security bhavcopy and cache it.

    python scripts/fetch_bhavcopy.py --days 260 --end 2026-08-21

Each file is gzipped on save (roughly 400 KB -> 90 KB); a full 260-day pull is
about 25 MB rather than 100 MB. Files already cached are never re-fetched, so
re-running is cheap and the script is safe to interrupt.

Non-trading days return 404. That is expected and skipped, not an error - NSE
publishes nothing for weekends and holidays.
"""
from __future__ import annotations

import argparse
import gzip
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{stamp}.csv"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CACHE = Path(__file__).resolve().parents[1] / "data" / "cache" / "bhavcopy"


def fetch_day(day: date, pause: float) -> str | None:
    """Return 'cached', 'fetched', 'holiday', or None on a hard failure."""
    stamp = day.strftime("%d%m%Y")
    out = CACHE / f"{stamp}.csv.gz"
    if out.exists():
        return "cached"

    req = Request(BASE.format(stamp=stamp), headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=45) as resp:
            body = resp.read()
    except HTTPError as exc:
        return "holiday" if exc.code == 404 else None
    except Exception:
        return None

    # A holiday page can come back 200 with an HTML body rather than a 404.
    if not body.lstrip()[:6].upper().startswith(b"SYMBOL"):
        return "holiday"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(body))
    time.sleep(pause)          # be a good citizen; these are free public files
    return "fetched"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=260, help="trading days wanted")
    ap.add_argument("--end", default="2026-08-21", help="most recent trading day")
    ap.add_argument("--pause", type=float, default=0.4)
    args = ap.parse_args()

    day = date.fromisoformat(args.end)
    got = fetched = holidays = failed = 0
    # Calendar headroom: ~250 trading days span ~360 calendar days.
    for _ in range(int(args.days * 1.6) + 30):
        if got >= args.days:
            break
        status = fetch_day(day, args.pause)
        if status in ("cached", "fetched"):
            got += 1
            fetched += status == "fetched"
        elif status == "holiday":
            holidays += 1
        else:
            failed += 1
        if got and got % 25 == 0 and status == "fetched":
            print(f"  {got}/{args.days} trading days ({day})", flush=True)
        day -= timedelta(days=1)

    print(
        f"done: {got} trading days cached ({fetched} newly fetched), "
        f"{holidays} non-trading days skipped, {failed} failures",
        flush=True,
    )
    return 1 if got < args.days * 0.9 else 0


if __name__ == "__main__":
    sys.exit(main())
