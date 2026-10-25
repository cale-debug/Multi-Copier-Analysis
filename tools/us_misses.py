"""Why do trades miss Polymarket US? Dump every recent miss next to what US actually lists.

    python tools/us_misses.py [wallet ...]   # default: every trader in settings.json on the data branch

Prints JSON lines to us_misses.jsonl and a summary to stdout. Diagnostic only.
"""
import json
import os
import sys
from collections import Counter

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot import live_us  # noqa: E402

D = "https://data-api.polymarket.com"
G = "https://gateway.polymarket.us"
S = requests.Session()


def get(url, params=None):
    try:
        r = S.get(url, params=params, timeout=20)
        return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:300])
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def wallets():
    if len(sys.argv) > 1:
        return sys.argv[1:]
    repo = os.environ.get("GITHUB_REPOSITORY", "cale-debug/Multi-Copier-Analysis")
    s = requests.get(f"https://raw.githubusercontent.com/{repo}/data/settings.json", timeout=20).json()
    return [s["target"]] + [b["target"] for b in s.get("books") or []]


def probe():
    """Find out which listing/search endpoints US offers."""
    out = {}
    for path, params in [("/v1/events", {"limit": 3}), ("/v1/events", {"limit": 3, "active": "true"}),
                         ("/v1/markets", {"limit": 3}), ("/v1/search", {"query": "Suns"}),
                         ("/v1/events/search", {"query": "Suns"}), ("/v1/sports", None), ("/v1/leagues", None),
                         ("/v1/series", None), ("/v1/events", {"limit": 3, "query": "Suns"}),
                         ("/v1/events", {"limit": 3, "search": "Suns"}), ("/v1/events", {"limit": 3, "league": "nba"})]:
        code, body = get(G + path, params)
        out[f"{path} {params}"] = [code, body if isinstance(body, str) else json.dumps(body)[:1500]]
    return out


def main():
    print("## US endpoint probe")
    for k, v in probe().items():
        print(f"- {k}: {v[0]} {v[1][:600]}")
    seen, misses, hits = set(), [], 0
    for w in wallets():
        code, acts = get(f"{D}/activity", {"user": w, "type": "TRADE", "limit": 500, "sortBy": "TIMESTAMP", "sortDirection": "DESC"})
        for a in acts if isinstance(acts, list) else []:
            if a.get("side") != "BUY":
                continue
            key = (a.get("eventSlug"), a.get("slug"), a.get("outcome"))
            if key in seen:
                continue
            seen.add(key)
            us_slug, long, why = live_us.match(a.get("slug") or "", a.get("eventSlug") or "", a.get("outcome") or "")
            if us_slug:
                hits += 1
                continue
            misses.append({"wallet": w[:10], "event": a.get("eventSlug"), "slug": a.get("slug"), "title": a.get("title"),
                           "outcome": a.get("outcome"), "why": why, "ts": a.get("timestamp")})
    print(f"\n## {hits} distinct markets matched, {len(misses)} missed")
    print("miss reasons:", Counter(m["why"] for m in misses).most_common())
    print("miss prefixes:", Counter((m["slug"] or "").split("-")[0] for m in misses).most_common(20))
    # What does US have for each missed event?
    events = {}
    for m in misses:
        ev = m["event"] or ""
        if ev in events:
            continue
        code, body = get(f"{G}/v1/events/slug/{ev}")
        e = (body.get("event") or body) if isinstance(body, dict) else {}
        events[ev] = {"code": code, "title": e.get("title"),
                      "markets": [{"slug": x.get("slug"), "q": x.get("question") or x.get("title"),
                                   "sides": [s.get("description") or s.get("name") or s.get("title") for s in (x.get("marketSides") or [])]}
                                  for x in e.get("markets") or []]}
    print("event lookups:", Counter(v["code"] for v in events.values()).most_common())
    with open("us_misses.jsonl", "w") as f:
        for m in misses:
            f.write(json.dumps({**m, "us_event": events.get(m["event"] or "")}) + "\n")
    # Print a readable sample: events US has (so the market didn't match), then events US 404s.
    found = [m for m in misses if events[m["event"] or ""]["code"] == 200]
    print(f"\n## {len(found)} misses where US HAS the event (market or side didn't line up)")
    shown = set()
    for m in found:
        if m["event"] in shown or len(shown) >= 40:
            continue
        shown.add(m["event"])
        ev = events[m["event"]]
        print(f"\n### {m['event']}  ({m['why']})")
        for x in [y for y in found if y["event"] == m["event"]][:6]:
            print(f"  intl: {x['slug']} | {x['title']} | {x['outcome']}")
        for u in ev["markets"][:25]:
            print(f"  US:   {u['slug']} | {u['q']} | {u['sides']}")
    nf = [m for m in misses if events[m["event"] or ""]["code"] != 200]
    print(f"\n## {len(nf)} misses where US has no event under that slug; sample:")
    for m in nf[:80]:
        print(f"  {m['event']} | {m['slug']} | {m['title']} | {m['outcome']}")


if __name__ == "__main__":
    main()
