# Rules of the live book (frozen on 25 November 2026)

These rules are written before the first live week. If I change one, the book becomes "v2"
and starts a new track record. I never rewrite the past.

1. **Universe**: the 11 SPDR sector ETFs: XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC.
2. **Signal**: total return (dividends included) over 11 months, from the end of month M-11 to the end of month M-1. The last month is skipped. Same code as the backtest (`backtest.momentum_signal`).
3. **Positions**: long the 3 best ETFs, short the 3 worst, one third of the capital each. 100% long, 100% short. Plain rule, no vol scaling (vol scaling does not help on ETFs in the backtest, see README section 6).
4. **Months**: a month runs from the last Friday of one month to the last Friday of the next.
5. **Rebalancing**: at the close of the last Friday of each month. No change during the month, whatever happens. Positions drift with prices between two rebalances.
6. **Publication**: thanks to the skipped month, the positions of the next rebalance are known one month in advance. They are committed to GitHub the weekend after the previous rebalance, a month before they are traded.
7. **Prices**: Bloomberg HP, field "Total Return" (Cumulative), photo taken on Friday. If the US market is closed on Friday (Christmas, New Year), I use Thursday's close and keep the Friday date.
8. **Costs**: 10 bp on every USD traded, plus 0.25% per year on the short notional (borrow).
9. **Capital**: 1,000,000 USD on paper. P&L in USD and in % of capital.
10. **Weekly report**: committed before Monday 09:00 Paris time. Every week is reported, good or bad. A missed Friday is written as missed, and its return is added to the next week.
