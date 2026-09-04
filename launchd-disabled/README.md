# Disabled launchd jobs — DeepThinkTrader

Removed from `~/Library/LaunchAgents/` on 2026-08-17 so they stop running and
do not return on login. These are the **live** copies as they existed at that
moment, which matters: the `bot` and `dashboard` plists at the repo root had
already drifted from what was actually installed, so they were not a usable
backup. `docs-sync` existed only in LaunchAgents and had no repo copy at all.

State when removed: `bot` had been up 6 days, `dashboard` 15 days (streamlit on
127.0.0.1:8501), `docs-sync` fired hourly via StartInterval, `migration` was
inert (RunAtLoad false, KeepAlive false). `TRADE_MODE=safe` in `.env`, with no
mode override in `tunable_params.json`, so the bot was not live-trading.

`bot` and `dashboard` both had `KeepAlive=true` — killing the processes would
have respawned them; they were stopped with `launchctl bootout` first.

## To restore one

    cp launchd-disabled/com.deepthinktrader.bot.plist ~/Library/LaunchAgents/
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.deepthinktrader.bot.plist
