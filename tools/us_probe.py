"""Probe Polymarket US for the shapes the matcher needs. Diagnostic only.

    python tools/us_probe.py
"""
import json

import requests

G = "https://gateway.polymarket.us"


def get(path, params=None):
    r = requests.get(G + path, params=params, timeout=20)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:300]


def short(e):
    return {k: e.get(k) for k in ("slug", "title", "startDate", "active", "closed", "seriesSlug", "sport", "league", "gameId")}


print("## search")
for q in ["Suns", "Warriors", "Nuggets", "Knicks", "Spurs", "Real Madrid", "Hoffenheim", "Orlando City", "G2", "T1",
          "Merab", "Machac", "Seahawks", "Celtics", "Bayern", "San Jose State", "Brewers"]:
    code, b = get("/v1/search", {"query": q})
    evs = b.get("events", []) if isinstance(b, dict) else []
    print(f"- {q}: {code} keys={list(b)[:6] if isinstance(b, dict) else ''} n={len(evs)}")
    for e in evs[:8]:
        print("   ", json.dumps(short(e)))
print("\n## search params")
for p in [{"query": "Suns", "limit": 50}, {"query": "Suns", "page": 2}, {"query": "Suns", "active": "true"},
          {"query": "nba-gsw-phx"}, {"query": "Warriors Suns"}]:
    code, b = get("/v1/search", p)
    evs = b.get("events", []) if isinstance(b, dict) else []
    print(f"- {p}: {code} n={len(evs)} {[e.get('slug') for e in evs[:12]]}")
print("\n## event listing filters")
for p in [{"limit": 5, "offset": 0, "closed": "false"}, {"limit": 5, "orderBy": "startDate", "ascending": "false"},
          {"limit": 5, "order": "startDate", "ascending": "false"}, {"limit": 5, "startDateMin": "2026-10-24T00:00:00Z"},
          {"limit": 5, "start_date_min": "2026-10-24T00:00:00Z"}, {"limit": 5, "seriesSlug": "nba"}, {"limit": 5, "tag": "nba"},
          {"limit": 5, "sport": "nba"}, {"limit": 5, "categories": "nba"}]:
    code, b = get("/v1/events", p)
    evs = b.get("events", []) if isinstance(b, dict) else []
    print(f"- {p}: {code} {[(e.get('slug'), e.get('startDate')) for e in evs[:5]]}")
print("\n## one full event (all markets) + market detail")
for ev in ["nba-hou-atl-2026-10-24", "cfb-sjst-nevada-2026-10-24", "cs2-fnc-prv-2026-10-20"]:
    code, b = get(f"/v1/events/slug/{ev}")
    e = (b.get("event") or b) if isinstance(b, dict) else {}
    print(f"\n### {ev}: {code} {len(e.get('markets') or [])} markets; event keys {sorted(e)[:40]}")
    for m in e.get("markets") or []:
        s = m.get("slug", "")
        if s.startswith(("aec-", "asc-", "tsc-")) and "-sh-" not in s and "-1h-" not in s and "-2h-" not in s and "-p1-" not in s:
            print("  ", s, "|", m.get("question"), "|", [(x.get("description"), x.get("long")) for x in m.get("marketSides") or []])
code, b = get("/v1/market/slug/asc-nba-hou-atl-2026-10-24-neg-1pt5")
print("\n## market detail", code, json.dumps(b)[:2500])
code, b = get("/v1/market/slug/tsc-nba-hou-atl-2026-10-24-219pt5")
print("\n## market detail", code, json.dumps(b)[:1500])
