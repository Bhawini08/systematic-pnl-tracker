import yfinance as yf
import pandas as pd

TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
START = "2022-01-01"
END = "2024-12-31"

def fetch_prices():
    raw = yf.download(TICKERS, start=START, end=END, auto_adjust=True)
    prices = raw["Close"]
    prices.index = prices.index.strftime("%Y-%m-%d")
    return prices

def momentum_signals(prices, lookback=20):
    """Buy if price is above its 20-day moving average, else sell."""
    ma = prices.rolling(lookback).mean()
    signals = (prices > ma).astype(int)  # 1 = long, 0 = flat
    signals = signals.shift(1).dropna()  # trade next day
    return signals

def mean_reversion_signals(prices, lookback=20, z_threshold=1.5):
    """Buy if price is z_threshold std devs below mean, sell if above."""
    ma = prices.rolling(lookback).mean()
    std = prices.rolling(lookback).std()
    z = (prices - ma) / std
    signals = pd.DataFrame(0, index=z.index, columns=z.columns)
    signals[z < -z_threshold] = 1   # oversold -> buy
    signals[z >  z_threshold] = -1  # overbought -> sell
    signals = signals.shift(1).dropna()
    return signals

if __name__ == "__main__":
    prices = fetch_prices()
    mom = momentum_signals(prices)
    mr = mean_reversion_signals(prices)
    print("Momentum signals shape:", mom.shape)
    print("Mean reversion signals shape:", mr.shape)
    print(mom.tail(3))
