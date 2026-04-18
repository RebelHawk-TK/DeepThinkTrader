---
title: Trader Bot — Onboarding Guide
subtitle: trader.travelforge.ai
author: Tom King
date: April 2026
---

# Welcome

The trader bot runs paper trades through your own Alpaca account on a shared strategy Tom has been developing. It's a friends-and-family preview: **paper money only, no real dollars, and nothing in this guide or the dashboard is financial advice.**

This guide walks you through every step — from creating an Alpaca account to reading the dashboard — plus troubleshooting and what the bot is actually doing under the hood.

Budget about 20 minutes to get set up.

---

# What you'll end up with

- A free Alpaca **paper** account (fake money, real market data)
- Access to the dashboard at **trader.travelforge.ai**
- A bot running cycles every 15 minutes during market hours, trading on your behalf
- A dashboard view of your trades, positions, P&L, research notes, and live logs

---

# Before you start

You need:

- A **Google account** you're willing to use for sign-in (Gmail, Workspace, whatever — the email you give Tom gets added to the access list)
- A **password manager** (1Password, Bitwarden, Apple Keychain — anything). Alpaca shows the API secret exactly once; losing it means regenerating.
- A **private channel** to Tom (Signal, iMessage, encrypted email). Do not send API keys over plain email or SMS.

---

# Step 1 — Create an Alpaca paper account

Alpaca is the broker that executes the trades. Their paper API trades fake money against real live market data, which is exactly what you want.

1. Open **https://app.alpaca.markets/signup**
2. Sign up with any email — no SSN, no bank details, no identity verification required for paper
3. Confirm your email, then sign in
4. On the dashboard, look at the top-left corner. You'll see a toggle between **Live Trading** and **Paper Trading**. Flip it to **Paper Trading**.

Every step below assumes Paper mode. Do not flip to Live — the bot is not ready for real money, and the keys Tom has are scoped to the paper endpoint anyway.

---

# Step 2 — Generate your API keys

1. In Paper mode, go to **Home** (left sidebar) and scroll to **Your API Keys** on the right side of the page
2. Click **Generate New Keys**
3. A panel shows two values:
   - **API Key ID** — 20 characters, uppercase
   - **Secret Key** — 40 characters, mixed case
4. **Copy both to your password manager right now.** The secret is displayed exactly once. If you close the panel without copying, you'll need to regenerate a new pair (which invalidates any pair Tom already has).

Keep these somewhere you won't accidentally share — they grant full control of your paper portfolio.

---

# Step 3 — Request an invite

Send Tom the Google email address you want to sign in with. Any Google-hosted address works (Gmail, Workspace, etc).

Contact: **tom@brigitteandtom.com**

Tom grants access to **trader.travelforge.ai** through Google Cloud IAP. Usually takes under a minute.

---

# Step 4 — Sign in

1. Open **https://trader.travelforge.ai**
2. You'll be redirected to Google sign-in. Use the email you gave Tom.
3. After sign-in you'll see either:
   - **The dashboard** (if Tom has already enabled your account), or
   - **"Account pending approval"** (if he hasn't yet). This is normal on first sign-in — ping Tom, he'll flip the toggle, and the next refresh shows the dashboard.

If you see a Google error like *"You don't have access"* instead of the sign-in page, the invite hasn't propagated yet. Wait 2–3 minutes and try again.

---

# Step 5 — Enter your API keys in the dashboard

On the left sidebar of trader.travelforge.ai, click **Settings**. You'll see a form with two fields:

1. **Alpaca API Key ID** — paste the 20-character key id (starts with `PK` for paper)
2. **Alpaca Secret Key** — paste the 40-character secret

Click **Test & save**. The dashboard pings Alpaca's paper endpoint with your credentials:

- On success, you'll see your paper account number, status, and cash balance, and the keys are saved encrypted in the database.
- On failure, you'll see the error Alpaca returned — usually either "keys rejected" (copy-paste issue, or you're still on the Live toggle) or a network error (transient, retry).

**Your keys are never transmitted over a side channel.** They go directly from the form to the dashboard's backend, encrypted with a key stored in GCP Secret Manager, and written to Postgres. Neither Tom nor anyone else sees them in plaintext.

You can rotate or delete keys anytime from the same page. Deleting stops the bot on your account at the next cycle.

---

# The dashboard — what's on each page

Once you're signed in, the left sidebar shows these pages:

## dashboard

The main view. Shows:

- **Portfolio summary** — cash, equity, today's P&L, lifetime P&L
- **Open positions** — every ticker currently held, with entry price, current price, unrealized P&L, stop level, target
- **Recent trades** — the last N closed trades, sortable by date, ticker, P&L
- **Scan results** — tickers the bot is currently watching and why
- **Research notes** — the DeepThink agent's writeups on each symbol (why it's interesting, key levels, thesis)

This is where you spend most of your time.

## Analytics

Performance stats over time:

- Edge performance — which setups actually made money vs. their backtested expectation
- Slippage analysis — how far actual fills drift from the prices the bot wanted
- Win rate, average win, average loss, expectancy by setup type

Useful for spotting whether the strategy is degrading or whether a specific setup is broken.

## Live Logs

Raw log tail from the bot. When something looks off, open this page and search for the ticker or a recent timestamp.

Three log streams available in a dropdown:

- **Bot** — the main cycle logs
- **Errors** — just ERROR-and-above lines
- **Scheduler** — the 15-minute cycle timing

Auto-refreshes every few seconds.

## Risk Dashboard

Portfolio-level risk metrics:

- Concentration (how much of the portfolio is in a single position)
- Drawdown (peak-to-trough decline)
- Daily and intraday exposure charts
- Correlation with the broader market (SPY beta, roughly)

If something red shows up here, the bot should already be throttling — but it's worth a glance after volatile days.

## Trade Detail

Click into an individual trade from the dashboard or Analytics page to see its full story:

- Entry reasoning (what the research agent said at the time)
- Edge score (the system's confidence)
- Price timeline (fills, stop moves, partial exits)
- Slippage on each fill
- Risk metrics (R-multiples, position size relative to account)

This is the best page to learn how the bot thinks.

## Settings

Enter, rotate, or delete your Alpaca paper API keys. See Step 5 for the initial flow. The page shows the last 4 characters of the key currently on file so you can tell which pair is active.

Rotation takes effect the next time the bot restarts (usually within a few hours during a scheduled redeploy). If you need an immediate switch, ping Tom.

## Admin

Only visible if Tom flags your account as admin. Regular users won't see this page.

---

# How the bot actually behaves

## Cycle timing

The scheduler runs a cycle **every 15 minutes, during US equity market hours** (9:30am–4pm Eastern, weekdays, excluding market holidays). Outside those hours the bot sleeps — logs will show "Market closed, sleeping until next open."

A cycle does, roughly:

1. Refresh prices for everything on the watchlist
2. Run the research agent on interesting setups (LLM-based analysis, so it takes a few seconds per symbol)
3. Compute entry/exit signals
4. Submit orders through Alpaca
5. Log everything and update the database

Nothing happens overnight or on weekends beyond housekeeping.

## Warmup period

On day one, the bot needs price history it doesn't have yet. Expect:

- Very few trades (possibly zero)
- Research notes showing "insufficient data" on some symbols
- ATR (volatility) calculations warming up over the first 14 market days

Give it at least a week before judging the outputs.

## Shared strategy, separate accounts

Everyone on the system runs the same watchlist, same entry rules, same risk limits. But your fills and P&L will drift from other users' because:

- Orders submit in sequence, not simultaneously — there's a few seconds between users
- Alpaca's paper engine simulates slippage per account
- Your cash level affects position sizing

Two users who both "took the same trade" will see slightly different entry prices and position sizes. That's normal.

## What the bot will and won't trade

- **Will:** US equities from the configured watchlist (large-cap tech and select mid-caps)
- **Will not:** options, crypto, leveraged ETFs, anything on a short-sale restriction, penny stocks
- **Will not:** place orders outside regular hours
- **Will not:** hold more than the configured concentration limit in any single name

---

# Monitoring your trades

Three places to cross-check:

1. **trader.travelforge.ai dashboard** — the bot's view. What it thinks happened.
2. **app.alpaca.markets (Paper mode) → Portfolio** — the broker's view. Ground truth on fills, cash, positions.
3. **Live Logs page** — the narrative. Why the bot did what it did.

If the dashboard and Alpaca disagree on position count or cash balance, the dashboard is stale — a cycle finished writing but the dashboard hasn't reloaded. Hit refresh.

If they still disagree after a refresh, that's a bug — ping Tom with a screenshot.

---

# Troubleshooting

**Can't reach trader.travelforge.ai at all (connection error, DNS error)**
: Wait 5 minutes — the invite may still be propagating. If still broken after 10 minutes, ping Tom.

**Google sign-in loops or says "You don't have access"**
: The IAP invite didn't land on the email you're signing in with. Double-check you gave Tom the right address.

**"Account pending approval" after signing in**
: Normal on first sign-in. Tom needs to flip your enabled toggle.

**Dashboard loads but shows no data**
: Either your Alpaca keys aren't wired up yet (Step 5), or the bot hasn't run a cycle for your account yet. Check Live Logs for your email — if it's not mentioned, the bot doesn't know about you yet.

**Alpaca shows positions but dashboard shows none**
: Either keys are wrong (bot can't see your account) or dashboard is stale. Refresh. If still empty, check Live Logs for authentication errors.

**Trades firing that look wrong**
: Open Trade Detail for the specific trade. If the reasoning doesn't hold up, screenshot + send to Tom. He can disable your account instantly while investigating.

**Want to pause the bot temporarily**
: Regenerate your Alpaca keys (old ones invalidate immediately), or ask Tom to flip your enabled toggle off. Both work; the second is faster to reverse.

---

# Stopping entirely

You can walk away anytime:

1. **Regenerate your Alpaca API keys** — the ones Tom has will stop working on the next cycle
2. **Ask Tom to delete your account** — revokes IAP access and removes your row from the system
3. **Close your Alpaca account** — paper accounts can be closed from the Alpaca settings page

No subscription, nothing to cancel.

---

# Risks and disclaimers

- **Paper only.** Do not copy your keys to the Live endpoint. Full stop. The bot has not been validated for real money.
- **Not financial advice.** The research notes and trade decisions are automated outputs from an experimental system. Treat them as a curiosity, not a recommendation.
- **No guarantees.** The strategy may lose paper money. It may have bugs. Tom may push a change that makes it worse. You get what you get.
- **Your keys, your responsibility.** If you leak your API secret, whoever has it can empty your paper account. Since it's fake money the blast radius is zero, but get in the habit of treating the secret like a real one — because when (if) this moves to live money, the habit matters.
- **Shared infrastructure.** Everyone runs on the same Cloud Run instance, same database, same rate limits. If Alpaca throttles one user, others may see delays. That's the tradeoff for this being free.

---

# Contact

Ping Tom directly. No help desk, no SLA, no Zendesk.

- Email: **tom@brigitteandtom.com**
- Signal / iMessage: ask Tom for his number

If Tom's unreachable and something looks truly broken (trades firing in a loop, balance going negative), regenerate your Alpaca keys — that's the emergency stop.
