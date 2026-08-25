"""Download NSE F&O (derivatives) bhavcopy and cache it.

    python scripts/fetch_fo_bhavcopy.py --days 60 --end 2026-08-21

Same stale-file trap as the cash bhavcopy (see fetch_bhavcopy.py): NSE answers
some non-trading stamps with the previous day's file. The UDiFF format carries
TradDt, which is checked against the requested stamp before anything is cached.
"""
from __future__ import annotations

import argparse
import io
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{stamp}_F_0000.csv.zip"
)
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CACHE = Path(__file__).resolve().parents[1] / "data" / "cache" / "fo"


def fetch_day(day: date, pause: float) -> str | None:
    stamp = day.strftime("%Y%m%d")
    out = CACHE / f"{stamp}.csv.zip"
    if out.exists():
        return "cached"

    req = Request(BASE.format(stamp=stamp), headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=60) as resp:
            body = resp.read()
    except HTTPError as exc:
        return "holiday" if exc.code == 404 else None
    except Exception:
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            inner = zf.namelist()[0]
            head = zf.open(inner).read(4096).decode("utf-8", "replace").splitlines()
        cols = [c.strip() for c in head[0].split(",")]
        traded = head[1].split(",")[cols.index("TradDt")].strip()
        if datetime.strptime(traded, "%Y-%m-%d").date() != day:
            return "stale"
    except Exception:
        return "holiday"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    time.sleep(pause)
    return "fetched"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--end", default="2026-08-21")
    ap.add_argument("--pause", type=float, default=0.3)
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
        f"done: {got} trading days cached ({fetched} newly fetched), "
        f"{holidays} skipped, {stale} stale rejected, {failed} failures",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
