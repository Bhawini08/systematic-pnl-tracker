import os
import numpy as np
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import create_engine

ROOT = os.path.dirname(__file__)
DB_PATH = os.path.join(ROOT, "data", "pnl_tracker.db")
engine = create_engine(f"sqlite:///{DB_PATH}")

st.set_page_config(page_title="Systematic PnL Tracker", layout="wide")
st.title("Systematic PnL Tracker")
st.caption("Momentum vs Mean Reversion | SPY, QQQ, IWM, GLD, TLT | 2022-2024")

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
if strategy_filter != "All":
    display = trades[trades["strategy"] == strategy_filter]
else:
    display = trades
st.dataframe(display.tail(50), use_container_width=True)
