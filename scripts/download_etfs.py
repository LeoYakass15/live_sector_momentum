"""Downloads the monthly prices of the 11 SPDR sector ETFs from Yahoo (free).
Adjusted close = price with dividends reinvested, so the return is a total return.
Run once:  python scripts/download_etfs.py
"""
import yfinance as yf

ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]

px = yf.download(ETFS, start="1998-12-01", end="2026-11-01", interval="1mo", auto_adjust=True)["Close"]
px.index = px.index + __import__("pandas").offsets.MonthEnd(0)   # Yahoo dates the month on the 1st
px[ETFS].round(4).to_csv("data/etf_monthly_yahoo.csv")
print(px.tail())
