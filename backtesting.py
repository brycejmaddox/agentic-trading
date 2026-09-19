import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from io import StringIO

end_date = pd.Timestamp.today() 
cutoff_date = end_date - pd.DateOffset(months=6)  # today minus 6 months
start_date = end_date - pd.DateOffset(months=30)  # today minus 30 months (2.5 years)

spx = yf.download("^GSPC", start=start_date, end=end_date)
spx.columns = spx.columns.droplevel(1)

spx["MA200"] = spx["Close"].rolling(window=200).mean()
spx["Regime200"] = spx["Close"] > spx["MA200"]

oos_regime200 = spx["Regime200"][(spx.index > cutoff_date) & (spx.index <= end_date)]

spx["MA50"] = spx["Close"].rolling(window=50).mean()
spx["Regime50"] = spx["Close"] > spx["MA50"]

oos_regime50 = spx["Regime50"][(spx.index > cutoff_date) & (spx.index <= end_date)]

account_size = 2000
risk_per_trade = account_size * 0.002
max_position_size = account_size *  0.15


def run_backtest(ticker,market_regime,risk_per_trade,max_position_size):
    data = yf.download(ticker, start=start_date, end=end_date)
    data.columns = data.columns.droplevel(1)

    data["MA200"] = data["Close"].rolling(window=200).mean()

    data["MarketRegime"] = market_regime.reindex(data.index)

    data["HL"] = data["High"] - data["Low"]
    data["HC"] = abs(data["High"] - data["Close"].shift(1))
    data["LC"] = abs(data["Low"] - data["Close"].shift(1))
    data["TrueRange"] = pd.concat([data["HL"], data["HC"], data["LC"]], axis=1).max(axis=1)
    data["ATR"] = data["TrueRange"].rolling(window=14).mean()
    data["Shares"] = risk_per_trade / data["ATR"]
    data["DollarExposure"] = data["Shares"] * data["Close"]

    data["DollarExposure"] = data["DollarExposure"].clip(upper=max_position_size)
    print(ticker, data["DollarExposure"].max())

    step_1 = data["Close"]
    data["Change"] = step_1.diff()
    data["Gain"] = data["Change"].clip(lower=0)
    data["Loss"] = data["Change"].clip(upper=0)
    data["Loss"] = abs(data["Loss"])
    data["AvgGain"] = data["Gain"].rolling(window=14).mean()
    data["AvgLoss"] = data["Loss"].rolling(window=14).mean()

    data["RS"] = data["AvgGain"] / data["AvgLoss"]
    data["RSI"] = 100 - (100 / (1 + data["RS"]))

    prior_RSI = data["RSI"].shift(1)

    data["BuySignal"] = (data["RSI"] < 30) & (data["RSI"].shift(1) >= 30) & (data["Close"] > data["MA200"]) & (data["MarketRegime"] == True)
    data["BuySignalNoRegime"] = (data["RSI"] < 30) & (data["RSI"].shift(1) >= 30) & (data["Close"] > data["MA200"])
    print(ticker, data["BuySignalNoRegime"].sum(), data["BuySignal"].sum())
    data["SellSignal"] = (data["RSI"] > 70) & (data["RSI"].shift(1) <= 70)

    in_position = False
    entry_price = None
    days_held = 0
    entry_date = None
    position_size = None
    entry_rsi = None
    trades = []
    for index, row in data.iterrows():
        if row["BuySignal"] == True and in_position == False and index > cutoff_date:
            in_position = True
            entry_price = row["Close"]
            entry_date = index
            position_size = row["DollarExposure"]
            entry_rsi = row["RSI"]
        elif in_position:
            days_held += 1


        if row["SellSignal"] == True and in_position == True:
            res = (row["Close"] - entry_price) / entry_price
            dollar_res = (res * position_size)
            in_position = False
            trades.append((entry_date, res, dollar_res, entry_rsi))
            entry_price = None
            days_held = 0
        elif days_held == 5:
            res = (row["Close"] - entry_price) / entry_price
            dollar_res = (res * position_size)
            in_position = False
            trades.append((entry_date, res, dollar_res, entry_rsi))
            days_held = 0
            entry_price = None
        elif in_position == True and row["Close"] <= (entry_price * 0.925):
            res = (row["Close"] - entry_price) / entry_price
            dollar_res = (res * position_size)
            in_position = False
            trades.append((entry_date, res, dollar_res, entry_rsi))
            days_held = 0
            entry_price = None
            
            

    winning_trades = [t for t in trades if t[1] > 0]
    try:
        win_rate = (len(winning_trades) / len(trades)) * 100
        avg_return = sum([t[1] for t in trades]) / len(trades)
    except ZeroDivisionError:
        win_rate = 0
        avg_return = 0

    return trades




headers = {"User-Agent": "Mozilla/5.0"}
response = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=headers)
soup = BeautifulSoup(response.text, "html.parser")
table = soup.find("table", {"id": "constituents"})
tables = pd.read_html(StringIO(str(table)))

sp500_tickers = tables[0]["Symbol"].tolist()

sector_etfs = ["XLF", "XLK", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"]

full_universe = sp500_tickers + sector_etfs

all_trades = []


for i in full_universe:
    try:
        all_trades.extend(run_backtest(i, spx["Regime50"], risk_per_trade,max_position_size))
    except Exception as e:
        print(e)
        print(i)

sorted_trades = sorted(all_trades, key=lambda t: t[0])

current_balance = account_size
compounding_equity_curve = []
for t in sorted_trades:
    risk_per_trade_now = current_balance * 0.002
    new_dollar_result = t[2] * (risk_per_trade_now / risk_per_trade)
    current_balance = current_balance + new_dollar_result
    compounding_equity_curve.append(current_balance)
real_running_peak = 0
real_drawdown = []
for bal in compounding_equity_curve:
    if bal > real_running_peak:
        real_running_peak = bal
    real_drawdown.append((bal - real_running_peak) / real_running_peak)

max_real_drawdown = min(real_drawdown)


total_dollar_return = sum([t[2] for t in sorted_trades])

all_returns = [t[1] for t in sorted_trades]

clean_trades = [c for c in all_returns if not pd.isna(c)]

all_winning_trades = [a for a in clean_trades if a > 0 ]

overall_win_rate = (len(all_winning_trades) / len(clean_trades)) * 100
overall_avg_return = sum(clean_trades) / len(clean_trades)


equity = 1
equity_curve = []
for t in clean_trades:
    equity = equity * (1 + t)
    equity_curve.append(equity)


running_peak = 0
drawdown = []
for current_equity in equity_curve:
    if current_equity > running_peak:
        running_peak = current_equity
    drawdown.append((current_equity - running_peak) / running_peak)

entry_dates = [t[0] for t in all_trades]
date_counts = pd.Series(entry_dates).value_counts()

grouped = {}
for date, ret, dollar_res, res_rsi in sorted_trades:
    if date not in grouped:
        grouped[date] = []
    grouped[date].append((ret, dollar_res, res_rsi))

capped_trades = []
cap = 4
for date, returns in grouped.items():
    ordered_returns = sorted(returns, key= lambda t: t[2])
    capped_trades.extend(ordered_returns[:cap])

all_capped_winning_trades = [a[0] for a in capped_trades if a[0] > 0 ]

capped_win_rate = (len(all_capped_winning_trades) / len(capped_trades)) * 100
capped_avg_dollar_return = sum([a[1] for a in capped_trades]) / len(capped_trades)
total_capped_dollar_return = sum([a[1] for a in capped_trades])


capped_equity = 1
capped_equity_curve = []
for t in capped_trades:
    capped_equity = capped_equity * (1 + t[0])
    capped_equity_curve.append(capped_equity)


capped_running_peak = 0
capped_drawdown = []
for capped_current_equity in capped_equity_curve:
    if capped_current_equity > capped_running_peak:
        capped_running_peak = capped_current_equity
    capped_drawdown.append((capped_current_equity - capped_running_peak) / capped_running_peak)


print(max_real_drawdown)
print(current_balance)
print(current_balance - account_size)
print(compounding_equity_curve[:5])
print(compounding_equity_curve[-5:])



print(total_dollar_return)
print(total_capped_dollar_return)
print(capped_avg_dollar_return)

print(capped_win_rate)
print(len(capped_trades))
print(min(capped_drawdown))
print("---------Below is baseline info---------")
print(overall_avg_return)
print(overall_win_rate)
print(len(clean_trades))
print(min(drawdown))