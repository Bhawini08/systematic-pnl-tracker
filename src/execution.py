import pandas as pd
from sqlalchemy import text
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))
from database import engine
from strategies import fetch_prices, momentum_signals, mean_reversion_signals

CAPITAL = 100000        # starting capital per strategy
SLIPPAGE_BPS = 5        # 5 basis points per trade

def run_backtest(signals, prices, strategy_name):
    trades = []
    position = pd.Series(0.0, index=prices.columns)  # shares held per ticker

    for date in signals.index:
        if date not in prices.index:
            continue

        price_today = prices.loc[date]
        sig_today = signals.loc[date]

        for ticker in signals.columns:
            sig = sig_today[ticker]
            pos = position[ticker]
            price = price_today[ticker]
            slippage = price * SLIPPAGE_BPS / 10000

            # Determine trade
            if sig == 1 and pos == 0:
                direction = "BUY"
                qty = round((CAPITAL / len(signals.columns)) / price, 2)
            elif sig == 0 and pos > 0:
                direction = "SELL"
                qty = pos
            elif sig == -1 and pos == 0:
                direction = "SELL"
                qty = round((CAPITAL / len(signals.columns)) / price, 2)
            else:
                continue

            # Update position
            if direction == "BUY":
                position[ticker] = qty
            else:
                position[ticker] = 0.0

            trades.append({
                "date": date,
                "ticker": ticker,
                "direction": direction,
                "quantity": qty,
                "price": price,
                "strategy": strategy_name,
                "slippage": slippage
            })

    return pd.DataFrame(trades)

def write_trades(df):
    with engine.connect() as conn:
        for _, row in df.iterrows():
            conn.execute(text("""
                INSERT INTO trades (date, ticker, direction, quantity, price, strategy, slippage)
                VALUES (:date, :ticker, :direction, :quantity, :price, :strategy, :slippage)
            """), row.to_dict())
        conn.commit()
    print(f"Wrote {len(df)} trades to database.")

if __name__ == "__main__":
    prices = fetch_prices()

    mom_signals = momentum_signals(prices)
    mom_trades = run_backtest(mom_signals, prices, "momentum")
    write_trades(mom_trades)

    mr_signals = mean_reversion_signals(prices)
    mr_trades = run_backtest(mr_signals, prices, "mean_reversion")
    write_trades(mr_trades)

    print("\nSample trades:")
    print(mom_trades.head())