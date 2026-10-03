import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from io import StringIO
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import os
from dotenv import load_dotenv

#Load environment variables
load_dotenv()
api_key = os.getenv("ALPACA_API_KEY")
api_secret = os.getenv("ALPACA_API_SECRET")
trading_client = TradingClient(api_key, api_secret, paper=True)

#Create exit signal function
def check_exit(ticker, entry_price, entry_date, entry_rsi):
    data = yf.download(ticker, period="1y")
    data.columns = data.columns.droplevel(1)

    step_1 = data["Close"]
    data["Change"] = step_1.diff()
    data["Gain"] = data["Change"].clip(lower=0)
    data["Loss"] = data["Change"].clip(upper=0)
    data["Loss"] = abs(data["Loss"])
    data["AvgGain"] = data["Gain"].rolling(window=14).mean()
    data["AvgLoss"] = data["Loss"].rolling(window=14).mean()

    data["RS"] = data["AvgGain"] / data["AvgLoss"]
    data["RSI"] = 100 - (100 / (1 + data["RS"]))

    current_data = data.iloc[-1]
    held_data = data[data.index >= entry_date]
    days_held = len(held_data) - 1
    previous_data = data.iloc[-2]

    if (current_data["RSI"] > 70) & (previous_data["RSI"] <= 70):
        return (True, ticker,  current_data["Close"])
    elif current_data["Close"] <= (entry_price * 0.925):
        return (True, ticker,  current_data["Close"])
    elif days_held >= 5:
        return (True, ticker,  current_data["Close"])
    else:
        return (False, None, None)

#From check_exit, sell chosen positions and update open_positions.csv with new positions
if os.path.exists("open_positions.csv"):
    positions_df = pd.read_csv("open_positions.csv", parse_dates=["entry_date"])

    tickers_to_remove = []
    for index, row in positions_df.iterrows():    
        try: 
            results = check_exit(row["ticker"], row["entry_price"], row["entry_date"], row["entry_rsi"])
            exit_flag, exit_ticker, exit_price = results
            print(f"{row['ticker']}, {exit_flag}")
            if exit_flag == True:
                submitted_order = trading_client.close_position(exit_ticker)
                tickers_to_remove.append(exit_ticker)
        except Exception as e: 
            print(e)
    remaining_positions = positions_df[~positions_df["ticker"].isin(tickers_to_remove)]
    remaining_positions.to_csv(
        "open_positions.csv",
        sep= ",",
        mode= "w",
        header= True,
        index= False
    )

#Import spx data to determine market regime to use
spx = yf.download("^GSPC", period="100d")
spx.columns = spx.columns.droplevel(1)

spx["MA50"] = spx["Close"].rolling(window=50).mean()
spx["Regime50"] = spx["Close"] > spx["MA50"]

today_regime = spx["Regime50"].iloc[-1]

#Create sigal check function to determine what stocks the buy today
def check_signal(ticker, ticker_data, market_regime):
    data = ticker_data

    data["MA200"] = data["Close"].rolling(window=200).mean()

    data["HL"] = data["High"] - data["Low"]
    data["HC"] = abs(data["High"] - data["Close"].shift(1))
    data["LC"] = abs(data["Low"] - data["Close"].shift(1))
    data["TrueRange"] = pd.concat([data["HL"], data["HC"], data["LC"]], axis=1).max(axis=1)
    data["ATR"] = data["TrueRange"].rolling(window=14).mean()

    step_1 = data["Close"]
    data["Change"] = step_1.diff()
    data["Gain"] = data["Change"].clip(lower=0)
    data["Loss"] = data["Change"].clip(upper=0)
    data["Loss"] = abs(data["Loss"])
    data["AvgGain"] = data["Gain"].rolling(window=14).mean()
    data["AvgLoss"] = data["Loss"].rolling(window=14).mean()

    data["RS"] = data["AvgGain"] / data["AvgLoss"]
    data["RSI"] = 100 - (100 / (1 + data["RS"]))

    today = data.iloc[-1]
    yesterday = data.iloc[-2]
    buy_signal_today = (today["RSI"] < 30) and (yesterday["RSI"] >= 30) and (today["Close"] > today["MA200"]) and market_regime

    return (ticker, buy_signal_today, today["RSI"], today["ATR"], today["Close"])

#Scrapping to get all spx tickers to run through check_signal
headers = {"User-Agent": "Mozilla/5.0"}
response = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=headers)
soup = BeautifulSoup(response.text, "html.parser")
table = soup.find("table", {"id": "constituents"})
tables = pd.read_html(StringIO(str(table)))

sp500_tickers = tables[0]["Symbol"].tolist()
sp500_tickers = [x.replace(".", "-") for x in sp500_tickers]

#Adding any etfs we want to consider, then creating the full universe of tickers
sector_etfs = ["XLF", "XLK", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"]

full_universe = sp500_tickers + sector_etfs

all_data = yf.download(full_universe, period= "1y", group_by= "ticker")

present_tickers = [t for t in full_universe if t in all_data.columns.get_level_values(0).unique()]

nan_tickers = [t for t in present_tickers if all_data[t]["Close"].isna().all()]

final_universe = [t for t in present_tickers if t not in nan_tickers]
#Run tickers through check_signal, collecting signals in a list
all_signals = []


for i in final_universe:
    try:
        all_signals.append(check_signal(i, all_data[i], today_regime))
    except Exception as e:
        print(e)
        print(i)

#From all_signals, we check to see what signals are "True" 
positions = trading_client.get_all_positions()
position_symbols = [p.symbol for p in positions]
if os.path.exists("open_positions.csv"):
    current_positions = pd.read_csv("open_positions.csv")
    bought_tickers = current_positions["ticker"].tolist()
else:
    bought_tickers = []
dont_buy = bought_tickers + position_symbols
todays_buys = [s for s in all_signals if s[1] == True and  s[0] not in dont_buy]


#Sort possible buys from lowest to highest RSI, then select lowest three RSIs
todays_sorted_buys = sorted(todays_buys, key= lambda t: t[2])

top_candidates = todays_sorted_buys[:3]


#Next, we need to determine if candidates have already been bought, so we check Alpaca positions and open_positions.csv
candidate_symbols = [t[0] for t in top_candidates]

buy_symbols = [t for t in candidate_symbols if t not in dont_buy]

with open("daily_runs.txt", "a") as f:
    f.write((f"{pd.Timestamp.today()}, {len(todays_buys)}, {dont_buy}, {todays_buys}, {top_candidates}, {buy_symbols}\n" ))

#Get current balance in Alpaca to determine risk and how much we could buy into a stock
account = trading_client.get_account()
current_balance = float(account.cash)
risk_per_trade = current_balance * 0.002
max_position_size = current_balance * 0.15

#Determine the size of the position
sized_orders = []
for t in top_candidates:
    if t[0] in buy_symbols:
        Shares = risk_per_trade / t[3]
        DollarExposure = Shares * t[4]
        buy_amount = min(DollarExposure, max_position_size)
        sized_orders.append((t[0], buy_amount))

#Finally, submit the order request, ensuring order amount is rounded to the nearest two decimal places
for order in sized_orders:
    symbol = order[0]
    amount = round(order[1], 2)
    # build the MarketOrderRequest using symbol and amount
    # submit it
    order_request = MarketOrderRequest(
    symbol=symbol,
    notional=amount,
    side=OrderSide.BUY,
    time_in_force=TimeInForce.DAY
    )
    try:
        submitted_order = trading_client.submit_order(order_request)
        with open("daily_orders.txt", "a") as o:
            o.write(f"{pd.Timestamp.today()}, {order}\n")

        #Add the new position to open_positions.csv for future reference

        match = [t for t in top_candidates if t[0] == symbol]
        new_row = {"ticker": match[0][0], "entry_date": pd.Timestamp.today().date(),
                    "entry_price": match[0][4], "entry_rsi": match[0][2]}
        csv_row = pd.DataFrame([new_row])
        if os.path.exists("open_positions.csv"):
            csv_row.to_csv(
                "open_positions.csv",
                sep = ",",
                mode = "a",
                header = False,
                index = False
            )
        else:
            csv_row.to_csv(
                "open_positions.csv",
                sep = ",",
                mode = "a",
                header = True,
                index = False
            )
            
    except Exception as e:
        with open("daily_orders.txt", "a") as o:
            o.write(f"{pd.Timestamp.today()}, Failure: {e}, {order}\n")
    