# Multi-Copier Analysis

Paper-trades copies of several Polymarket traders at once, one $3,000 paper book
per trader, so they can be compared side by side before any of them is copied
with real money. Built from PolyCopier but fully separate from it: its own
schedule, its own `data` branch and dashboard, and no Polymarket keys, so it can
never place a real trade.

- **Bot** (`bot/`): one GitHub Actions job runs every book. Each book polls its
  trader every few seconds and copies buys and sells into its own paper account,
  priced off the Polymarket US order book, with US fees, slippage and filters.
  Only markets also listed on Polymarket US are copied.
- **Dashboard** (`docs/`, GitHub Pages): a table and P&L chart comparing every
  trader; tap one to see its book. Add or remove traders there.
- **State** (`data` branch): `settings.json` (the traders and shared rules),
  `state-paper.json` / `state-paper-<id>.json` (one per book) and `books.json`
  (the comparison summary).
- **Check trader** workflow: sizes up any usernames or wallets (style, red flags,
  share of their bets that are on Polymarket US).

Runs free only while the repo is public (unlimited Actions minutes and free Pages).
