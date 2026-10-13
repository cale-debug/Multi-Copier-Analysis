"""Keep the roster at the best 10 traders who can be copied on Polymarket US.

    python tools/roster.py            # GitHub Actions: reads/writes settings.json on the data branch
    python tools/roster.py --dry-run  # print what would change

Runs once a day. A trader comes off the roster when they:
  - haven't traded for QUIET_DAYS (taking a break),
  - are down for the month on the leaderboard (fell off),
  - stopped betting in markets that are on Polymarket US, or
  - lost money in our own paper copy after a fair trial (MIN_TRIAL_DAYS and MIN_TRIAL_CLOSED).
Each one is replaced by the best eligible trader from the Sports/Esports boards who
isn't already on it. Dropped traders sit out COOLDOWN_DAYS before they can return.
A report of the ranking and every change goes to roster.json for the dashboard.
"""
import argparse
import base64
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_leaderboard as scan  # noqa: E402

ROSTER = 10
QUIET_DAYS = 3
MIN_US = 0.25          # share of their recent buys that are on Polymarket US, to join
KEEP_US = 0.15         # ...and to stay
MIN_WIN = 0.60
MAX_FLIP = 0.5         # sells most buys within an hour: a delayed copy misses that
MIN_TRIAL_DAYS = 7
MIN_TRIAL_CLOSED = 30
COOLDOWN_DAYS = 14
DAY = 86400


class Repo:
    def __init__(self, repo, token):
        self.api = f"https://api.github.com/repos/{repo}/contents"
        self.h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    def read(self, path):
        r = requests.get(f"{self.api}/{path}", headers=self.h, params={"ref": "data"}, timeout=30)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        b = r.json()
        if not b.get("content"):
            raw = requests.get(f"{self.api}/{path}", params={"ref": "data"}, timeout=60,
                               headers={**self.h, "Accept": "application/vnd.github.raw"})
            return raw.json(), b["sha"]
        return json.loads(base64.b64decode(b["content"])), b["sha"]

    def write(self, path, data, sha, msg):
        body = {"message": msg, "branch": "data", "content": base64.b64encode(json.dumps(data, indent=1).encode()).decode()}
        if sha:
            body["sha"] = sha
        return requests.put(f"{self.api}/{path}", headers=self.h, json=body, timeout=30).ok


def lb_pnl(wallet):
    out = {}
    for per in ("MONTH", "ALL"):
        r = scan.rows(scan.get(f"{scan.D}/v1/leaderboard", {"timePeriod": per, "orderBy": "PNL", "user": wallet}))
        if r:
            out[per] = r[0]
    return out


def evaluate(wallet, name):
    lb = lb_pnl(wallet)
    return scan.score(wallet, name, {p: lb.get(p, {}) for p in ("ALL", "MONTH", "WEEK")})


def rank(r):
    # Consistency (the scan's score), weighted by how much of it a US account can actually copy.
    base = r["win"] * 50 + (r["weeks_green"] / max(1, r["weeks"])) * 30 + max(-20, min(20, r["roi"] * 100))
    return base * (0.5 + r["us"])


def eligible(r, now):
    if r is None:
        return "not enough history"
    if now - r["last_trade"] > QUIET_DAYS * DAY:
        return f"no trades for {QUIET_DAYS}+ days"
    if r["pnl_month"] <= 0 or r["pnl_all"] <= 0:
        return "not profitable on the leaderboard"
    if r["us"] < MIN_US:
        return f"only {r['us']:.0%} on Polymarket US"
    if r["win"] < MIN_WIN:
        return f"win rate {r['win']:.0%}"
    if r["flip"] > MAX_FLIP:
        return "sells most buys within an hour"
    return None


def why_drop(book, r, paper, now):
    """Why a trader on the roster should come off, or None to keep them."""
    if r is None:
        return "no recent trading history"
    if now - r["last_trade"] > QUIET_DAYS * DAY:
        return f"no trades for {QUIET_DAYS}+ days"
    if r["pnl_month"] < 0:
        return f"down ${-r['pnl_month']:,.0f} this month"
    if r["us"] < KEEP_US:
        return f"only {r['us']:.0%} of recent bets on Polymarket US"
    if paper and paper.get("started_at") and now - paper["started_at"] > MIN_TRIAL_DAYS * DAY \
            and paper.get("wins", 0) + paper.get("losses", 0) >= MIN_TRIAL_CLOSED and paper.get("pnl", 0) < 0:
        return f"our paper copy is down ${-paper['pnl']:,.2f} after {int((now - paper['started_at']) / DAY)} days"
    return None


def slug(label, taken):
    base = "".join(c if c.isalnum() else "-" for c in label.lower()).strip("-")[:32] or "trader"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pool", type=int, default=300)
    args = ap.parse_args()
    repo = Repo(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    now = int(time.time())
    settings, sha = repo.read("settings.json")
    books_now, _ = repo.read("books.json")
    paper = {b["id"]: b for b in (books_now or {}).get("books", [])}
    dropped = {w: t for w, t in (settings.get("roster_dropped") or {}).items() if now - t < COOLDOWN_DAYS * DAY}

    roster = [{"id": "main", "label": settings.get("target_label", ""), "target": settings.get("target", "")}]
    roster += [b for b in settings.get("books") or [] if b.get("id") != "main" and b.get("target")]
    changes, kept = [], []
    for b in roster:
        r = evaluate(b["target"], b.get("label"))
        why = why_drop(b, r, paper.get(b["id"]), now)
        if why:
            changes.append({"out": b.get("label"), "wallet": b["target"], "why": why})
            dropped[b["target"]] = now
        else:
            kept.append(b)
        print(f"- {b.get('label')}: {'OUT, ' + why if why else 'stays'}")

    # Candidates from the Sports and Esports leaderboards (what Polymarket US lists), best first.
    boards = {p: {} for p in ("ALL", "MONTH", "WEEK")}
    for cat in ("SPORTS", "ESPORTS"):
        scan.CATEGORY = cat
        for p in boards:
            for w, row in scan.board(p, args.pool).items():
                boards[p].setdefault(w, row)
    have = {b["target"].lower() for b in kept}
    cands = []
    for w in boards["MONTH"]:
        if w in have or w in dropped or not all(w in boards[p] and scan.f(boards[p][w].get("pnl")) > 0 for p in ("ALL", "MONTH")):
            continue
        r = scan.score(w, boards["ALL"][w].get("userName"), {p: boards[p].get(w, {}) for p in boards})
        bad = eligible(r, now)
        if r:
            r["rank"], r["skip"] = rank(r), bad
            cands.append(r)
    cands.sort(key=lambda r: -r["rank"])
    pool = [r for r in cands if not r["skip"]]

    taken = {b["id"] for b in kept}
    added = []
    while len(kept) + len(added) < ROSTER and pool:
        r = pool.pop(0)
        bid = slug(r["name"], taken)
        taken.add(bid)
        added.append({"id": bid, "label": r["name"], "target": r["wallet"], "halted": False})
        changes.append({"in": r["name"], "wallet": r["wallet"],
                        "why": f"{r['win']:.0%} win rate, {r['us']:.0%} on Polymarket US, ${r['pnl_month']:,.0f} this month"})
        print(f"+ {r['name']} ({r['wallet']})")

    main_kept = any(b["id"] == "main" for b in kept)
    new = dict(settings)
    extra = [b for b in kept if b["id"] != "main"] + added
    if not main_kept and extra:
        # The main book's trader came off: the best newcomer (or longest-standing book) takes it over, fresh.
        first = extra.pop(0) if not added else extra.pop(extra.index(added[0]))
        new.update(target=first["target"], target_label=first["label"], reset_paper=True, halted=False)
    new["books"] = [{**b, "halted": bool(b.get("halted"))} for b in extra]
    new["roster_dropped"] = dropped
    report = {"updated": now, "changes": changes,
              "ranking": [{k: r[k] for k in ("name", "wallet", "win", "us", "pnl_month", "pnl_all", "per_day", "rank", "skip")}
                          for r in cands[:40]]}
    if args.dry_run:
        print(json.dumps({"books": new["books"], "main": new.get("target_label"), "changes": changes}, indent=1))
        return
    if changes:
        cur, sha = repo.read("settings.json")   # re-read right before writing, so a dashboard edit isn't lost
        cur.update(books=new["books"], roster_dropped=dropped)
        if not main_kept:
            cur.update({k: new[k] for k in ("target", "target_label", "reset_paper", "halted")})
        print("settings saved" if repo.write("settings.json", cur, sha, f"Roster: {len(changes)} change(s)") else "settings save FAILED")
    old, rsha = repo.read("roster.json")
    if old:
        report["history"] = ([{"at": now, **c} for c in changes] + old.get("history", []))[:200]
    else:
        report["history"] = [{"at": now, **c} for c in changes]
    repo.write("roster.json", report, rsha, "Roster report")


if __name__ == "__main__":
    main()
