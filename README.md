🔗 [Live Dashboard](https://systematic-pnl-tracker.streamlit.app)
# Systematic PnL Tracker

End-to-end systematic trading infrastructure combining Python and SQL — from signal generation to persistent trade storage to performance analytics.

## Architecture
- **Strategy Layer** — Momentum and mean-reversion signals across 5 ETFs (SPY, QQQ, IWM, GLD, TLT)
- **Execution Layer** — Signal-to-trade conversion with slippage modeling, all trades written to SQLite
- **Database Layer** — 3-table schema (trades, positions, daily_pnl) tracking 1,364 trades across 3 years
- **Analytics Layer** — Rolling Sharpe, max drawdown attribution, and strategy correlation via SQL queries

## Key Findings
- Momentum and mean-reversion strategies exhibit -0.40 correlation, providing natural diversification
- Mean-reversion achieved lower max drawdown (-20%) vs momentum (-113%) over 2022-2024
- SQL-backed rolling Sharpe computed via 30-day window functions across both strategies

## Stack
Python, SQLite, SQLAlchemy, pandas, yfinancegit add README.md && git commit -m "Add README" && git push
