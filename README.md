# Agentic Trading — RSI Mean-Reversion Strategy

An algorithmic trading system that scans the S&P 500 and major sector ETFs daily for oversold mean-reversion opportunities, sizes positions based on volatility, and can trade them automatically through a live paper-trading pipeline.

The project has two parts: a **backtesting engine** used to validate the strategy historically, and a **live automated trading script** that runs unattended on a daily schedule against Alpaca's paper trading API.

---

## Strategy

**Universe:** S&P 500 constituents (scraped live from Wikipedia) plus 11 major sector ETFs — roughly 514 tickers.

**Entry signal:**
- RSI(14) drops below 30 (oversold)
- Price is above its 200-day moving average (long-term trend filter)
- The S&P 500 itself is above its own 50-day moving average (market regime filter, to avoid buying dips during a broad downtrend)

**Exit — whichever comes first:**
- RSI crosses back above 70
- 7.5% stop-loss from entry
- 5 trading days held (time-based exit)

**Position sizing:** ATR-based — position size scales inversely with a stock's recent volatility (Average True Range), so risk per trade stays roughly consistent across very different stocks. Sized to risk ~0.2% of account equity per trade, capped at 15% of account value per position.

**Entry cap:** Up to 3 new positions per day, prioritized by lowest RSI (most oversold) when multiple signals fire on the same day.

---

## Backtest Results

Tested across the full ~514-ticker universe, using a 6-month out-of-sample window on a simulated $2,000 starting account, with real ATR-based position sizing:

| Metric | Value |
|---|---|
| Return | +13.9% ($2,000 → $2,277.28) |
| Max drawdown | -7.9% |
| Win rate | 55.3% (441 trades) |
| Avg. return per trade | 0.76% |

*These are backtested/simulated results, not a live trading track record.*

---

## Live Deployment

`check_signal.py` runs the strategy end-to-end against Alpaca's paper trading API, scheduled to run automatically once per weekday via Windows Task Scheduler:

- Scrapes the current S&P 500 ticker list and pulls live price/volume data via yfinance
- Checks and closes any open positions that have hit an exit condition
- Scans the full universe for new entry signals, sizes and submits new orders
- Tracks open positions in a local CSV (ticker, entry date, entry price, entry RSI) so state persists across independent daily runs
- Includes safeguards against duplicate order submission (checking both live Alpaca positions and pending/unfilled orders) and per-ticker error isolation so one bad data pull doesn't crash the full run


---

## Tech Stack

Python, pandas, yfinance, Alpaca Trading API (`alpaca-py`), BeautifulSoup, Windows Task Scheduler, python-dotenv.

---

## Setup

1. Clone the repo and install dependencies:
```
   pip install yfinance pandas requests beautifulsoup4 alpaca-py python-dotenv
```
2. Create a `.env` file in the project root with your Alpaca paper trading credentials:
```
   ALPACA_API_KEY=your_key_here
   ALPACA_API_SECRET=your_secret_here
```
3. Run the backtest:
```
   python backtesting.py
```
4. Run the live signal check (requires an active Alpaca paper account):
```
   python check_signal.py
```

---

## Known Limitations

This strategy has been validated on a single 6-month out-of-sample window and has several open questions that would need addressing before treating it as a robust, production-ready edge:

- **Single test window:** results reflect one 6-month period and haven't been validated across multiple non-overlapping windows or market regimes.
- **Survivorship bias:** the backtest applies today's S&P 500 constituent list retroactively across the full lookback period, excluding companies that were removed from the index during that time — this tends to inflate historical returns.
- **No transaction costs or slippage modeled:** real-world returns across 441+ trades would likely be somewhat lower.
- **No correlation check across same-day picks:** multiple positions opened on the same day aren't checked for sector/factor correlation, so daily picks may not be as diversified as they appear.
- **Fixed RSI thresholds:** the 30/70 RSI levels are applied uniformly across all 514 tickers regardless of each stock's own volatility profile.
- **Regime filter limitations:** the 200-day MA trend filter doesn't fully protect against sharp short-term declines in an otherwise long-term uptrending stock.

---

*Built as a personal project to explore mean-reversion trading strategies, quantitative position sizing, and end-to-end automated trading pipelines.*