import os
import sys
import numpy as np
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import create_engine, text

ROOT = os.path.dirname(__file__)
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "pnl_tracker.db")
engine = create_engine(f"sqlite:///{DB_PATH}")

def setup_database():
    import yfinance as yf

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL, ticker TEXT NOT NULL,
                direction TEXT NOT NULL, quantity REAL NOT NULL,
                price REAL NOT NULL, strategy TEXT NOT NULL,
                slippage REAL DEFAULT 0.0)"""))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_pnl (
                date TEXT NOT NULL, strategy TEXT NOT NULL,
                realized_pnl REAL DEFAULT 0.0, unrealized_pnl REAL DEFAULT 0.0,
                nav REAL NOT NULL, drawdown REAL DEFAULT 0.0,
                PRIMARY KEY (date, strategy))"""))
        conn.commit()

    count = pd.read_sql("SELECT COUNT(*) as n FROM trades", engine)["n"][0]
    if count > 0:
        return

    TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
    raw = yf.download(TICKERS, start="2022-01-01", end="2024-12-31", auto_adjust=True)
    prices = raw["Close"]
    prices.index = prices.index.strftime("%Y-%m-%d")

    def momentum_signals(prices, lookback=20):
        return (prices > prices.rolling(lookback).mean()).astype(int).shift(1).dropna()

    def mean_reversion_signals(prices, lookback=20, z=1.5):
        ma = prices.rolling(lookback).mean()
        std = prices.rolling(lookback).std()
        zscore = (prices - ma) / std
        sig = pd.DataFrame(0, index=zscore.index, columns=zscore.columns)
        sig[zscore < -z] = 1
        sig[zscore > z] = -1
        return sig.shift(1).dropna()

    def run_backtest(signals, prices, strategy_name):
        trades, position = [], pd.Series(0.0, index=prices.columns)
        CAPITAL = 100000
        for date in signals.index:
            if date not in prices.index:
                continue
            for ticker in signals.columns:
                sig = signals.loc[date, ticker]
                pos = position[ticker]
                price = prices.loc[date, ticker]
                slip = price * 5 / 10000
                if sig == 1 and pos == 0:
                    qty = round((CAPITAL / len(signals.columns)) / price, 2)
                    position[ticker] = qty
                    trades.append({"date": date, "ticker": ticker, "direction": "BUY", "quantity": qty, "price": price, "strategy": strategy_name, "slippage": slip})
                elif sig == 0 and pos > 0:
                    trades.append({"date": date, "ticker": ticker, "direction": "SELL", "quantity": pos, "price": price, "strategy": strategy_name, "slippage": slip})
                    position[ticker] = 0.0
                elif sig == -1 and pos == 0:
                    qty = round((CAPITAL / len(signals.columns)) / price, 2)
                    position[ticker] = qty
                    trades.append({"date": date, "ticker": ticker, "direction": "SELL", "quantity": qty, "price": price, "strategy": strategy_name, "slippage": slip})
        return pd.DataFrame(trades)

    for strat_name, signals in [("momentum", momentum_signals(prices)), ("mean_reversion", mean_reversion_signals(prices))]:
        df = run_backtest(signals, prices, strat_name)
        with engine.connect() as conn:
            for _, row in df.iterrows():
                conn.execute(text("INSERT INTO trades (date,ticker,direction,quantity,price,strategy,slippage) VALUES (:date,:ticker,:direction,:quantity,:price,:strategy,:slippage)"), row.to_dict())
            conn.commit()

    pnl_query = """
        SELECT date, strategy,
               SUM(CASE WHEN direction='SELL' THEN quantity*(price-slippage)
                        WHEN direction='BUY' THEN -quantity*(price+slippage)
                        ELSE 0 END) AS realized_pnl
        FROM trades GROUP BY date, strategy ORDER BY date"""
    df = pd.read_sql(pnl_query, engine)
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
        for _, row in result.iterrows():
            conn.execute(text("INSERT INTO daily_pnl (date,strategy,realized_pnl,unrealized_pnl,nav,drawdown) VALUES (:date,:strategy,:realized_pnl,:unrealized_pnl,:nav,:drawdown)"),
                {"date": row["date"], "strategy": row["strategy"], "realized_pnl": row["realized_pnl"], "unrealized_pnl": row["unrealized_pnl"], "nav": row["nav"], "drawdown": row["drawdown"]})
        conn.commit()

st.set_page_config(page_title="Systematic PnL Tracker", layout="wide")
st.title("Systematic PnL Tracker")
st.caption("Momentum vs Mean Reversion | SPY, QQQ, IWM, GLD, TLT | 2022-2024")

with st.spinner("Loading data..."):
    setup_database()

@st.cache_data
def load_pnl():
    return pd.read_sql("SELECT * FROM daily_pnl ORDER BY date", engine)

@st.cache_data
def load_trades():
    return pd.read_sql("SELECT * FROM trades ORDER BY date", engine)

pnl = load_pnl()
trades = load_trades()

st.subheader("Strategy Summary")
col1, col2, col3, col4 = st.columns(4)
colors = {"momentum": "#00C4FF", "mean_reversion": "#FF6B6B"}

for strat, grp in pnl.groupby("strategy"):
    final_nav = grp["nav"].iloc[-1]
    max_dd = grp["drawdown"].min()
    total_return = (final_nav - 100000) / 100000 * 100
    n_trades = len(trades[trades["strategy"] == strat])
    if strat == "momentum":
        with col1:
            st.metric("Momentum - Final NAV", f"${final_nav:,.0f}")
            st.metric("Momentum - Total Return", f"{total_return:.1f}%")
        with col2:
            st.metric("Momentum - Max Drawdown", f"{max_dd:.1%}")
            st.metric("Momentum - Trades", n_trades)
    else:
        with col3:
            st.metric("Mean Rev - Final NAV", f"${final_nav:,.0f}")
            st.metric("Mean Rev - Total Return", f"{total_return:.1f}%")
        with col4:
            st.metric("Mean Rev - Max Drawdown", f"{max_dd:.1%}")
            st.metric("Mean Rev - Trades", n_trades)

st.divider()

st.subheader("NAV Over Time")
fig_nav = go.Figure()
for strat, grp in pnl.groupby("strategy"):
    fig_nav.add_trace(go.Scatter(x=grp["date"], y=grp["nav"], name=strat.replace("_", " ").title(), line=dict(color=colors[strat], width=2)))
fig_nav.update_layout(yaxis_title="NAV ($)", xaxis_title="Date", legend=dict(orientation="h", y=1.1), height=350, margin=dict(t=20, b=20))
st.plotly_chart(fig_nav, use_container_width=True)

st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Drawdown")
    fig_dd = go.Figure()
    for strat, grp in pnl.groupby("strategy"):
        fig_dd.add_trace(go.Scatter(x=grp["date"], y=grp["drawdown"] * 100, name=strat.replace("_", " ").title(), fill="tozeroy", line=dict(color=colors[strat], width=1.5)))
    fig_dd.update_layout(yaxis_title="Drawdown (%)", height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_dd, use_container_width=True)

with col_b:
    st.subheader("Rolling 30-Day Sharpe")
    fig_sharpe = go.Figure()
    for strat, grp in pnl.groupby("strategy"):
        grp = grp.sort_values("date").set_index("date")
        roll = grp["realized_pnl"].rolling(30)
        sharpe = (roll.mean() / roll.std()) * np.sqrt(252)
        fig_sharpe.add_trace(go.Scatter(x=sharpe.index, y=sharpe.values, name=strat.replace("_", " ").title(), line=dict(color=colors[strat], width=1.5)))
    fig_sharpe.update_layout(yaxis_title="Sharpe Ratio", height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_sharpe, use_container_width=True)

st.divider()

st.subheader("Trade Log")
strategy_filter = st.selectbox("Filter by strategy", ["All", "momentum", "mean_reversion"])
display = trades[trades["strategy"] == strategy_filter] if strategy_filter != "All" else trades
st.dataframe(display.tail(50), use_container_width=True)
