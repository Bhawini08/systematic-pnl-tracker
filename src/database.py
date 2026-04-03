import os
from sqlalchemy import create_engine, text

# Always points to data/pnl_tracker.db relative to project root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(ROOT, "data", "pnl_tracker.db")
engine = create_engine(f"sqlite:///{DB_PATH}")

def create_tables():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                direction   TEXT NOT NULL,
                quantity    REAL NOT NULL,
                price       REAL NOT NULL,
                strategy    TEXT NOT NULL,
                slippage    REAL DEFAULT 0.0
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS positions (
                date            TEXT NOT NULL,
                ticker          TEXT NOT NULL,
                quantity        REAL NOT NULL,
                avg_cost        REAL NOT NULL,
                market_value    REAL NOT NULL,
                unrealized_pnl  REAL NOT NULL,
                PRIMARY KEY (date, ticker)
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_pnl (
                date            TEXT NOT NULL,
                strategy        TEXT NOT NULL,
                realized_pnl    REAL DEFAULT 0.0,
                unrealized_pnl  REAL DEFAULT 0.0,
                nav             REAL NOT NULL,
                drawdown        REAL DEFAULT 0.0,
                PRIMARY KEY (date, strategy)
            )
        """))

        conn.commit()
        print("Tables created successfully.")

if __name__ == "__main__":
    create_tables()