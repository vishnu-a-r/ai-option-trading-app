"""Download NSE daily index close files and cache them.

    python scripts/fetch_index_close.py --days 340 --end 2026-08-21

One file per trading day, ~17 KB, covering 165 index series - Nifty 500 (the
relative-strength benchmark), the broad indices, and the sectorals.

Same stale-file trap as the cash bhavcopy: NSE answers some non-trading stamps
with the previous day's file. The "Index Date" column is checked against the
requested stamp before anything is cached.
"""
from __future__ import annotations

import argparse
import gzip
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{stamp}.csv"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CACHE = Path(__file__).resolve().parents[1] / "data" / "cache" / "index"


def _dates_match(body: bytes, day: date) -> bool:
    """Index Date is DD-MM-YYYY, unlike the bhavcopy's DD-Mon-YYYY."""
    try:
        first = body.split(b"\n", 2)[1].decode("utf-8", "replace")
        stamp = first.split(",")[1].strip()
        return datetime.strptime(stamp, "%d-%m-%Y").date() == day
    except (IndexError, ValueError):
        return False


def fetch_day(day: date, pause: float) -> str | None:
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

    if not body.lstrip()[:10].upper().startswith(b"INDEX NAME"):
        return "holiday"
    if not _dates_match(body, day):
        return "stale"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(body))
    time.sleep(pause)
    return "fetched"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=340)
    ap.add_argument("--end", default="2026-08-21")
    ap.add_argument("--pause", type=float, default=0.4)
    args = ap.parse_args()

    day = date.fromisoformat(args.end)
    got = fetched = holidays = stale = failed = 0
    for _ in range(int(args.days * 1.6) + 30):
        if got >= args.days:
            break
        status = fetch_day(day, args.pause)
        if status in ("cached", "fetched"):
            got += 1
            fetched += status == "fetched"
        elif status == "holiday":
            holidays += 1
        elif status == "stale":
            stale += 1
        else:
            failed += 1
        day -= timedelta(days=1)

    print(
        f"done: {got} trading days cached ({fetched} newly fetched), {holidays} skipped, "
        f"{stale} stale rejected, {failed} failures",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
