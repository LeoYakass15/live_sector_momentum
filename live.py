"""
Live paper trading of the sector book (11 SPDR ETFs, long the 3 best, short the 3 worst).

Every Friday I take a Bloomberg photo of the total return of the 11 ETFs and add one line
to data/bloomberg/live/weekly_returns.csv (date, then the weekly total return of each ETF,
from the previous Friday close to this Friday close, in decimal).

A "month" is the period between two last-Fridays-of-the-month. The signal skips the most
recent month, so the positions for the end of month M+1 are known at the end of month M:
I publish them one month BEFORE I trade them.

    python live.py positions   -> after the last Friday of a month: positions for the next rebalance
    python live.py week        -> every weekend: P&L of the week, chart, block for LIVE.md
"""
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import backtest as bt

CAPITAL = 1_000_000                     # paper capital in USD (change here for 1 billion)
N_LEGS = 3                              # 3 ETFs long, 3 ETFs short
WEEKLY = "data/bloomberg/live/weekly_returns.csv"
POSITIONS = "results/positions_live.csv"
PNL = "results/live_pnl.csv"
NAMES = {"XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health Care",
         "XLI": "Industrials", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
         "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication"}


def last_friday(month_end):
    d = pd.Timestamp(month_end) + pd.offsets.MonthEnd(0)
    return d - pd.Timedelta(days=(d.weekday() - 4) % 7)


def load_weekly():
    try:
        w = pd.read_csv(WEEKLY, index_col=0, parse_dates=True)
    except FileNotFoundError:
        w = pd.DataFrame(columns=bt.ETFS)
    return w[bt.ETFS].astype(float).sort_index()


def monthly_returns():
    """Yahoo history, replaced by the Bloomberg photos from Nov 2025 to Oct 2026,
    then the live months built from the weekly Bloomberg returns."""
    ret = bt.load_etfs()
    cum = pd.read_csv("data/bloomberg/etf_cumulative_total_return.csv", index_col=0, parse_dates=True)
    bbg = (1 + cum / 100).pct_change().iloc[1:]
    bbg.index = bbg.index + pd.offsets.MonthEnd(0)
    ret = pd.concat([ret.loc[:bbg.index[0] - pd.Timedelta(days=1)], bbg[bt.ETFS]])

    weekly = load_weekly()
    month = ret.index[-1] + pd.offsets.MonthEnd(1)
    while len(weekly) and last_friday(month) <= weekly.index[-1]:     # a complete live month
        start, end = last_friday(month - pd.offsets.MonthEnd(1)), last_friday(month)
        ret.loc[month] = (1 + weekly.loc[start + pd.Timedelta(days=1):end]).prod() - 1
        month += pd.offsets.MonthEnd(1)
    return ret


def new_positions():
    ret = monthly_returns()
    m = ret.index[-1]                                   # last complete month
    ret.loc[m + pd.offsets.MonthEnd(1)] = np.nan        # the month to come, skipped by the signal
    signal = bt.momentum_signal(ret).iloc[-1].dropna().sort_values(ascending=False)
    weight = pd.Series(0.0, index=signal.index)
    weight.iloc[:N_LEGS], weight.iloc[-N_LEGS:] = 1 / N_LEGS, -1 / N_LEGS
    trade_date = last_friday(m + pd.offsets.MonthEnd(1))

    table = pd.DataFrame({"trade_date": trade_date.date(), "etf": signal.index,
                          "signal": signal.round(4).values, "weight": weight.round(4).values})
    old = pd.read_csv(POSITIONS) if pd.io.common.file_exists(POSITIONS) else pd.DataFrame()
    if len(old):
        old = old[old.trade_date != str(trade_date.date())]
    pd.concat([old, table]).to_csv(POSITIONS, index=False)

    start = (m - pd.offsets.MonthEnd(11)).strftime("%b %Y")
    print(f"### Positions traded at the close of Friday {trade_date:%d %B %Y}\n")
    print(f"Signal: total return from end of {(m - pd.offsets.MonthEnd(11)):%B %Y} to end of {m:%B %Y}"
          f" (11 months, the last month is skipped).\n")
    print("| Rank | ETF | Sector | Signal | Position |\n|---|---|---|---|---|")
    for i, (etf, s) in enumerate(signal.items(), 1):
        side = "**Long**" if weight[etf] > 0 else ("**Short**" if weight[etf] < 0 else "-")
        print(f"| {i} | {etf} | {NAMES[etf]} | {s:+.1%} | {side} |")


def simulate():
    """Rebuilds the whole live track record from the files: weekly returns + positions."""
    weekly, pos = load_weekly(), pd.read_csv(POSITIONS, parse_dates=["trade_date"])
    nav, notional, rows = CAPITAL, pd.Series(0.0, index=bt.ETFS), []
    for d, r in weekly.iterrows():
        traded = pos[pos.trade_date < d]
        if traded.empty:
            continue
        cost = 0.0
        last_trade = traded.trade_date.max()
        if not rows or rows[-1]["trade_date"] != last_trade:          # rebalance at the last Friday's close
            w = traded[traded.trade_date == last_trade].set_index("etf")["weight"].reindex(bt.ETFS).fillna(0)
            new = w * nav
            cost = (new - notional).abs().sum() * bt.COST
            notional = new
        pnl_etf = notional * r.fillna(0)
        borrow = notional[notional < 0].abs().sum() * bt.BORROW / 52
        pnl = pnl_etf.sum() - cost - borrow
        rows.append({"date": d, "trade_date": last_trade, "pnl_usd": pnl, "pnl_pct": pnl / nav,
                     "long_usd": pnl_etf[notional > 0].sum(), "short_usd": pnl_etf[notional < 0].sum(),
                     "costs_usd": cost + borrow, "nav": nav + pnl, "detail": pnl_etf.copy(), "notional": notional.copy()})
        nav += pnl
        notional = notional * (1 + r.fillna(0))                     # positions drift with prices
    return rows


def weekly_report():
    rows = simulate()
    if not rows:
        print("No live week yet."); return
    hist = pd.DataFrame(rows).drop(columns=["detail", "notional"])
    hist["cumulative"] = hist.nav / CAPITAL - 1
    hist.drop(columns="trade_date").to_csv(PNL, index=False, float_format="%.4f")
    last, r = rows[-1], load_weekly().iloc[-1]
    dd = (hist.nav / hist.nav.cummax() - 1).iloc[-1]

    print(f"### Week {len(rows)}, ending Friday {last['date']:%d %B %Y}\n")
    print("| ETF | Sector | Position | Notional (USD) | Week return | P&L (USD) |\n|---|---|---|---|---|---|")
    for etf in last["notional"][last["notional"] != 0].sort_values(ascending=False).index:
        n = last["notional"][etf]
        print(f"| {etf} | {NAMES[etf]} | {'Long' if n > 0 else 'Short'} | {n:+,.0f} | {r[etf]:+.2%} |"
              f" {last['detail'][etf]:+,.0f} |")
    print(f"\nLong leg {last['long_usd']:+,.0f} USD, short leg {last['short_usd']:+,.0f} USD,"
          f" costs {-last['costs_usd']:,.0f} USD.")
    print(f"**Week: {last['pnl_pct']:+.2%} ({last['pnl_usd']:+,.0f} USD). Since launch: "
          f"{hist.cumulative.iloc[-1]:+.2%}. NAV {last['nav']:,.0f} USD. Drawdown {dd:.1%}.**")
    live_chart(hist)


def live_chart(hist):
    """Live P&L against what the ETF backtest expects (mean, 1 and 2 standard deviations)."""
    bt_pnl = pd.read_csv("results/monthly_pnl_etf.csv", index_col=0)["pnl"]
    mu, sigma = bt_pnl.mean() * 12 / 52, bt_pnl.std() * np.sqrt(12) / np.sqrt(52)
    weeks = np.arange(0, len(hist) + 1)
    plt.figure(figsize=(8, 4))
    for k, a in [(2, 0.12), (1, 0.25)]:
        plt.fill_between(weeks, mu * weeks - k * sigma * np.sqrt(weeks), mu * weeks + k * sigma * np.sqrt(weeks),
                         color="tab:blue", alpha=a, lw=0)
    plt.plot(weeks, mu * weeks, color="tab:blue", ls="--", label="Backtest expectation (1 and 2 std)")
    plt.plot(weeks, np.r_[0, hist.cumulative.values], color="black", lw=2, marker="o", label="Live")
    plt.axhline(0, color="grey", lw=0.8)
    plt.xlabel("Weeks since launch"); plt.ylabel("Cumulative return"); plt.legend(loc="upper left")
    plt.title("Live vs backtest"); plt.tight_layout(); plt.savefig("results/5_live_vs_backtest.png", dpi=120)
    plt.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "positions":
        new_positions()
    else:
        weekly_report()
