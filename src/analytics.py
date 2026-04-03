import os
import pandas as pd
import numpy as np
from sqlalchemy import text
from database import engine


def compute_daily_pnl():
    """Compute daily PnL per strategy from trades table and write to daily_pnl."""
    query = """
        SELECT date, strategy,
               SUM(CASE WHEN direction = 'SELL' THEN quantity * (price - slippage)
                        WHEN direction = 'BUY'  THEN -quantity * (price + slippage)
                        ELSE 0 END) AS realized_pnl
        FROM trades
        GROUP BY date, strategy
        ORDER BY date
    """
    df = pd.read_sql(query, engine)

    # Compute NAV and drawdown per strategy
    rows = []
    for strat, grp in df.groupby("strategy"):
        grp = grp.sort_values("date").reset_index(drop=True)
        grp["nav"] = 100000 + grp["realized_pnl"].cumsum()
        grp["peak"] = grp["nav"].cummax()
        grp["drawdown"] = (grp["nav"] - grp["peak"]) / grp["peak"]
        grp["unrealized_pnl"] = 0.0
        rows.append(grp)

    result = pd.concat(rows)

    with engine.connect() as conn:
        conn.execute(text("DELETE FROM daily_pnl"))
        for _, row in result.iterrows():
            conn.execute(text("""
                INSERT INTO daily_pnl (date, strategy, realized_pnl, unrealized_pnl, nav, drawdown)
                VALUES (:date, :strategy, :realized_pnl, :unrealized_pnl, :nav, :drawdown)
            """), {
                "date": row["date"],
                "strategy": row["strategy"],
                "realized_pnl": row["realized_pnl"],
                "unrealized_pnl": row["unrealized_pnl"],
                "nav": row["nav"],
                "drawdown": row["drawdown"]
            })
        conn.commit()
    print("Daily PnL written to database.")
    return result

def rolling_sharpe(window=30):
    """Compute rolling Sharpe ratio using SQL-backed daily PnL."""
    query = """
        SELECT date, strategy, realized_pnl
        FROM daily_pnl
        ORDER BY date
    """
    df = pd.read_sql(query, engine)
    results = {}
    for strat, grp in df.groupby("strategy"):
        grp = grp.sort_values("date").set_index("date")
        roll = grp["realized_pnl"].rolling(window)
        sharpe = (roll.mean() / roll.std()) * np.sqrt(252)
        results[strat] = sharpe
    return pd.DataFrame(results)

def max_drawdown_by_strategy():
    """Query max drawdown per strategy directly from SQL."""
    query = """
        SELECT strategy,
               MIN(drawdown) AS max_drawdown,
               MAX(nav)      AS peak_nav,
               MIN(nav)      AS trough_nav
        FROM daily_pnl
        GROUP BY strategy
    """
    return pd.read_sql(query, engine)

def strategy_correlation():
    """Compute correlation of daily PnL between strategies."""
    query = """
        SELECT date, strategy, realized_pnl
        FROM daily_pnl
    """
    df = pd.read_sql(query, engine)
    pivot = df.pivot(index="date", columns="strategy", values="realized_pnl")
    return pivot.corr()

if __name__ == "__main__":
    compute_daily_pnl()

    print("\nRolling Sharpe (last 5 days):")
    print(rolling_sharpe().tail())

    print("\nMax Drawdown by Strategy:")
    print(max_drawdown_by_strategy())

    print("\nStrategy Correlation:")
    print(strategy_correlation())