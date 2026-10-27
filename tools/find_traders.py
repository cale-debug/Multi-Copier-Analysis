"""Find traders worth copying on Polymarket US: enough history, a high win rate, and bets US lists.

    python tools/find_traders.py --pool 500 --min-closed 100 --min-win 0.70 --min-us 0.5

Candidates come from the Sports and Esports leaderboards (all-time and monthly, profitable
on both). Each is measured on up to 500 recent closed positions and their last 500 trades;
the US share uses the copier's own matcher (bot/live_us.match), so it counts what the bot
would actually copy. Prints a markdown table and writes finds.json (qualifiers, best first).
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import scan_leaderboard as scan  # noqa: E402
from bot import live_us  # noqa: E402

DAY = 86400


def us_share(wallet, n=80):
    acts = scan.rows(scan.get(f"{scan.D}/activity", {"user": wallet, "type": "TRADE", "limit": 300,
                                                     "sortBy": "TIMESTAMP", "sortDirection": "DESC"}))
    seen, hits = set(), 0
    for a in acts:
        key = (a.get("slug"), a.get("outcome"))
        if a.get("side") != "BUY" or key in seen:
            continue
        seen.add(key)
        _, _, why = live_us.match(a.get("slug") or "", a.get("eventSlug") or "", a.get("outcome"), a.get("title") or "")
        hits += why in ("", "US market closed")
        if len(seen) >= n:
            break
    return hits / len(seen) if seen else 0.0, len(seen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=500)
    ap.add_argument("--min-closed", type=int, default=100)
    ap.add_argument("--min-win", type=float, default=0.70)
    ap.add_argument("--min-us", type=float, default=0.50)
    ap.add_argument("--quiet-days", type=int, default=3)
    args = ap.parse_args()
    boards = {p: {} for p in ("ALL", "MONTH", "WEEK")}
    for cat in ("SPORTS", "ESPORTS"):
        scan.CATEGORY = cat
        for p in boards:
            for w, row in scan.board(p, args.pool).items():
                boards[p].setdefault(w, row)
    wallets = [w for w in boards["MONTH"] if w in boards["ALL"] and all(scan.f(boards[p][w].get("pnl")) > 0 for p in ("ALL", "MONTH"))]
    print(f"{len(wallets)} wallets profitable all-time and this month on the Sports/Esports boards (top {args.pool})\n")
    now, out, why = int(time.time()), [], {}
    for w in wallets:
        r = scan.score(w, boards["ALL"][w].get("userName"), {p: boards[p].get(w, {}) for p in boards})
        if not r:
            why["too little history"] = why.get("too little history", 0) + 1
            continue
        bad = ("fewer than %d closed" % args.min_closed if r["closed"] < args.min_closed else
               "win rate under %d%%" % (args.min_win * 100) if r["win"] < args.min_win else
               "quiet" if now - r["last_trade"] > args.quiet_days * DAY else
               "flipper" if r["flip"] > 0.5 else None)
        if not bad:
            r["us"], r["us_n"] = us_share(w)
            bad = "under %d%% on US" % (args.min_us * 100) if r["us"] < args.min_us else None
        if bad:
            why[bad.split(" (")[0]] = why.get(bad, 0) + 1
            continue
        out.append(r)
    out.sort(key=lambda r: -(r["win"] * r["us"]))
    print("filtered out:", why, "\n")
    print("| # | Trader | Win rate (closed) | On PM US | Month P&L | All-time P&L | Trades/day | Median bet | Both sides | Topics | Wallet |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(out, 1):
        print(f"| {i} | {r['name']} | {r['win']:.0%} ({r['closed']}) | {r['us']:.0%} of {r['us_n']} | ${r['pnl_month']:,.0f} | "
              f"${r['pnl_all']:,.0f} | {r['per_day']:,.0f} | ${r['median_bet']:,.0f} | {r['both_sides']:.0%} | {r['topics']} | `{r['wallet']}` |")
    with open("finds.json", "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
