import os
import numpy as np
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from sqlalchemy import create_engine, text

ROOT = os.path.dirname(__file__)
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "pnl_tracker.db")
engine = create_engine(f"sqlite:///{DB_PATH}")

st.set_page_config(page_title="Systematic PnL Tracker", layout="wide", page_icon="📈")

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .metric-container { background: #1a1a2e; border-radius: 10px; padding: 12px; }
    h1 { font-size: 2rem !important; }
    h2 { font-size: 1.2rem !important; color: #a0aec0 !important; font-weight: 400 !important; }
    .stMetric { background: #16213e; border-radius: 8px; padding: 10px 14px; }
    .stMetric label { color: #a0aec0 !important; font-size: 0.75rem !important; }
    .stMetric [data-testid="metric-container"] { gap: 2px; }
    div[data-testid="stSelectbox"] label { color: #a0aec0; font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

COLORS = {"momentum": "#00C4FF", "mean_reversion": "#FF6B6B"}
TICKER_COLORS = {"SPY": "#00C4FF", "QQQ": "#FF6B6B", "IWM": "#48BB78", "GLD": "#ECC94B", "TLT": "#9F7AEA"}

def setup_database():
    import yfinance as yf
    with engine.connect() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, ticker TEXT NOT NULL,
            direction TEXT NOT NULL, quantity REAL NOT NULL,
            price REAL NOT NULL, strategy TEXT NOT NULL,
            slippage REAL DEFAULT 0.0)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS daily_pnl (
            date TEXT NOT NULL, strategy TEXT NOT NULL,
            realized_pnl REAL DEFAULT 0.0, unrealized_pnl REAL DEFAULT 0.0,
            nav REAL NOT NULL, drawdown REAL DEFAULT 0.0,
            PRIMARY KEY (date, strategy))"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS ticker_pnl (
            date TEXT NOT NULL, ticker TEXT NOT NULL, strategy TEXT NOT NULL,
            pnl REAL DEFAULT 0.0, PRIMARY KEY (date, ticker, strategy))"""))
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

        ticker_pnl = df.copy()
        ticker_pnl["pnl"] = np.where(ticker_pnl["direction"] == "SELL",
            ticker_pnl["quantity"] * (ticker_pnl["price"] - ticker_pnl["slippage"]),
            -ticker_pnl["quantity"] * (ticker_pnl["price"] + ticker_pnl["slippage"]))
        tp = ticker_pnl.groupby(["date", "ticker"])["pnl"].sum().reset_index()
        tp["strategy"] = strat_name
        with engine.connect() as conn:
            for _, row in tp.iterrows():
                conn.execute(text("INSERT OR REPLACE INTO ticker_pnl (date,ticker,strategy,pnl) VALUES (:date,:ticker,:strategy,:pnl)"),
                    {"date": row["date"], "ticker": row["ticker"], "strategy": strat_name, "pnl": row["pnl"]})
            conn.commit()

    pnl_query = """SELECT date, strategy,
        SUM(CASE WHEN direction='SELL' THEN quantity*(price-slippage)
                 WHEN direction='BUY' THEN -quantity*(price+slippage) ELSE 0 END) AS realized_pnl
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

@st.cache_data
def load_pnl():
    return pd.read_sql("SELECT * FROM daily_pnl ORDER BY date", engine)

@st.cache_data
def load_trades():
    return pd.read_sql("SELECT * FROM trades ORDER BY date", engine)

@st.cache_data
def load_ticker_pnl():
    return pd.read_sql("SELECT * FROM ticker_pnl ORDER BY date", engine)

with st.spinner("Building strategy database from market data... this takes ~30 seconds on first load."):
    setup_database()

pnl = load_pnl()
trades = load_trades()
ticker_pnl = load_ticker_pnl()

# Header
st.title("📈 Systematic PnL Tracker")
st.markdown("##### Momentum vs Mean Reversion &nbsp;|&nbsp; SPY · QQQ · IWM · GLD · TLT &nbsp;|&nbsp; 2022–2024", unsafe_allow_html=True)
st.divider()

# Sidebar filters
with st.sidebar:
    st.markdown("### Filters")
    strategy_filter = st.selectbox("Strategy", ["Both", "momentum", "mean_reversion"])
    date_range = st.date_input("Date Range", value=[pd.to_datetime("2022-01-01"), pd.to_datetime("2024-12-31")])
    st.markdown("---")
    st.markdown("**About**")
    st.markdown("Vectorized backtest engine with SQL-backed PnL tracking. Signals → execution → persistent storage → analytics.")

start_date = str(date_range[0]) if len(date_range) == 2 else "2022-01-01"
end_date = str(date_range[1]) if len(date_range) == 2 else "2024-12-31"
pnl_f = pnl[(pnl["date"] >= start_date) & (pnl["date"] <= end_date)]
trades_f = trades[(trades["date"] >= start_date) & (trades["date"] <= end_date)]
if strategy_filter != "Both":
    pnl_f = pnl_f[pnl_f["strategy"] == strategy_filter]
    trades_f = trades_f[trades_f["strategy"] == strategy_filter]

# KPI cards
st.subheader("Strategy Summary")
cols = st.columns(4)
metrics = []
for strat, grp in pnl_f.groupby("strategy"):
    final_nav = grp["nav"].iloc[-1]
    max_dd = grp["drawdown"].min()
    total_return = (final_nav - 100000) / 100000 * 100
    n_trades = len(trades_f[trades_f["strategy"] == strat])
    metrics.append((strat, final_nav, total_return, max_dd, n_trades))

for i, (strat, nav, ret, dd, nt) in enumerate(metrics):
    label = strat.replace("_", " ").title()
    with cols[i * 2]:
        st.metric(f"{label} — NAV", f"${nav:,.0f}", f"{ret:+.1f}%")
    with cols[i * 2 + 1]:
        st.metric(f"{label} — Max DD", f"{dd:.1%}")
        st.metric(f"{label} — Trades", nt)

st.divider()

# NAV + Drawdown
col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("NAV Over Time")
    fig_nav = go.Figure()
    for strat, grp in pnl_f.groupby("strategy"):
        fig_nav.add_trace(go.Scatter(x=grp["date"], y=grp["nav"],
            name=strat.replace("_", " ").title(),
            line=dict(color=COLORS.get(strat, "#fff"), width=2)))
    fig_nav.update_layout(height=300, margin=dict(t=10, b=20),
        legend=dict(orientation="h", y=1.15),
        yaxis_title="NAV ($)", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_nav, use_container_width=True)

with col2:
    st.subheader("Drawdown")
    fig_dd = go.Figure()
    for strat, grp in pnl_f.groupby("strategy"):
        fig_dd.add_trace(go.Scatter(x=grp["date"], y=grp["drawdown"] * 100,
            name=strat.replace("_", " ").title(),
            fill="tozeroy", line=dict(color=COLORS.get(strat, "#fff"), width=1.5)))
    fig_dd.update_layout(height=300, margin=dict(t=10, b=20),
        yaxis_title="Drawdown (%)", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_dd, use_container_width=True)

st.divider()

# Rolling Sharpe + Correlation heatmap
col3, col4 = st.columns([3, 2])

with col3:
    st.subheader("Rolling 30-Day Sharpe")
    fig_sharpe = go.Figure()
    for strat, grp in pnl_f.groupby("strategy"):
        grp = grp.sort_values("date").set_index("date")
        roll = grp["realized_pnl"].rolling(30)
        sharpe = (roll.mean() / roll.std()) * np.sqrt(252)
        fig_sharpe.add_trace(go.Scatter(x=sharpe.index, y=sharpe.values,
            name=strat.replace("_", " ").title(),
            line=dict(color=COLORS.get(strat, "#fff"), width=1.5)))
    fig_sharpe.update_layout(height=300, margin=dict(t=10, b=20),
        yaxis_title="Sharpe Ratio", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_sharpe, use_container_width=True)

with col4:
    st.subheader("Strategy Correlation")
    pivot = pnl_f.pivot_table(index="date", columns="strategy", values="realized_pnl")
    corr = pivot.corr()
    fig_corr = px.imshow(corr, text_auto=".2f", color_continuous_scale="RdBu_r",
        zmin=-1, zmax=1, aspect="auto")
    fig_corr.update_layout(height=300, margin=dict(t=10, b=20),
        paper_bgcolor="rgba(0,0,0,0)", coloraxis_showscale=False)
    st.plotly_chart(fig_corr, use_container_width=True)

st.divider()

# Ticker PnL breakdown
st.subheader("PnL by Ticker")
tp_f = ticker_pnl[(ticker_pnl["date"] >= start_date) & (ticker_pnl["date"] <= end_date)]
if strategy_filter != "Both":
    tp_f = tp_f[tp_f["strategy"] == strategy_filter]
ticker_summary = tp_f.groupby("ticker")["pnl"].sum().reset_index().sort_values("pnl", ascending=True)
fig_ticker = go.Figure(go.Bar(
    x=ticker_summary["pnl"], y=ticker_summary["ticker"],
    orientation="h",
    marker_color=[TICKER_COLORS.get(t, "#888") for t in ticker_summary["ticker"]]))
fig_ticker.update_layout(height=250, margin=dict(t=10, b=20),
    xaxis_title="Total PnL ($)", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
st.plotly_chart(fig_ticker, use_container_width=True)

st.divider()

# Trade log
st.subheader("Trade Log")
st.dataframe(trades_f.sort_values("date", ascending=False).head(100), use_container_width=True)
