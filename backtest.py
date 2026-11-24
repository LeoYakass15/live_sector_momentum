"""
Industry momentum (Moskowitz and Grinblatt, 1999).

Rule: at each month-end, rank the 49 US industries on their return over the last 12 months,
skipping the most recent month. Buy the 10 best, sell short the 10 worst, equal weights.
Hold for one month, then rank again.

Run:  python backtest.py
Data: Ken French Data Library (free), 1926-2026, and SPDR sector ETFs (Yahoo, free).
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm, skew, kurtosis
import statsmodels.api as sm

# ---------------------------------------------------------------- settings
LOOKBACK = 12            # months in the ranking window...
SKIP = 1                 # ...minus the most recent month (short-term reversal)
N_LEGS = 10              # industries in each leg (10 long, 10 short)
COST = 0.0010            # 10 bp each time I buy or sell 1 USD
BORROW = 0.0025          # 0.25% per year to borrow the shorts
PUBLICATION = "1998-12-31"   # the paper was published in 1999: after this date = out-of-sample
ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]


# ---------------------------------------------------------------- 1. data
def read_ken_french(file, skiprows):
    """Ken French files: several tables one after the other. Keep the first one (monthly)."""
    df = pd.read_csv(f"data/ken_french/{file}", skiprows=skiprows, index_col=0)
    df.index = df.index.astype(str).str.strip()
    first_bad = np.argmax(~df.index.str.fullmatch(r"\d{6}"))   # end of the monthly table
    df = df.iloc[:first_bad] if first_bad > 0 else df
    df.index = pd.to_datetime(df.index, format="%Y%m") + pd.offsets.MonthEnd(0)
    df.columns = df.columns.str.strip()
    df = df.astype(float).replace([-99.99, -999], np.nan)
    return df / 100                                            # percent -> decimal


def load_industries():
    return read_ken_french("49_Industry_Portfolios.csv", 11)   # value-weighted returns


def load_factors():
    ff = read_ken_french("F-F_Research_Data_Factors.csv", 4)
    mom = read_ken_french("F-F_Momentum_Factor.csv", 13)
    return ff.join(mom)                                        # Mkt-RF, SMB, HML, RF, Mom


def load_etfs():
    px = pd.read_csv("data/etf_monthly_yahoo.csv", index_col=0, parse_dates=True)
    return px[ETFS].pct_change(fill_method=None).iloc[1:]


# ---------------------------------------------------------------- 2. strategy
def momentum_signal(ret, lookback=LOOKBACK, skip=SKIP):
    """Return from month t-lookback+1 to month t-skip, known at the end of month t."""
    window = lookback - skip
    past = np.log1p(ret).shift(skip).rolling(window).sum()     # a month with no data -> NaN
    return np.expm1(past)


def run_strategy(ret, lookback=LOOKBACK, skip=SKIP, n_legs=N_LEGS):
    """Monthly P&L of the long/short book (after costs) and the weights held each month.
    If the last row of ret is empty (next month), its weights are the positions to take now."""
    signal = momentum_signal(ret, lookback, skip)
    rank = signal.rank(axis=1, ascending=False)                # 1 = best industry
    n = signal.notna().sum(axis=1)
    long = (rank <= n_legs).astype(float)
    short = (rank > n.values[:, None] - n_legs).astype(float) * signal.notna()
    weight = long.div(long.sum(axis=1), axis=0) - short.div(short.sum(axis=1), axis=0)
    weight = weight.fillna(0)

    # weights decided at the end of month t are held during month t+1 (no look-ahead)
    weight = weight.shift(1).fillna(0)
    gross = (weight * ret.fillna(0)).sum(axis=1)
    turnover = weight.diff().abs().sum(axis=1)                 # USD traded per USD of capital
    cost = turnover * COST + BORROW / 12 * (weight < 0).any(axis=1)
    pnl = (gross - cost)[weight.abs().sum(axis=1) > 0]
    return pnl, weight


def vol_scaled(pnl, target=0.12, window=6):
    """The one fix I allow myself for momentum crashes (Barroso and Santa-Clara, 2015):
    cut the size when the strategy has been volatile over the last 6 months."""
    vol = pnl.rolling(window).std().shift(1) * np.sqrt(12)
    return (pnl * (target / vol).clip(upper=2)).dropna()


# ---------------------------------------------------------------- 3. statistics
def stats(pnl):
    n = len(pnl)
    sr = pnl.mean() / pnl.std() * np.sqrt(12)
    nav = (1 + pnl).cumprod()
    return {
        "Return (ann.)": pnl.mean() * 12,
        "Vol (ann.)": pnl.std() * np.sqrt(12),
        "Sharpe": sr,
        "t-stat": sr * np.sqrt(n / 12),            # = mean / (std / sqrt(n))
        "Max drawdown": (nav / nav.cummax() - 1).min(),
        "Skew": skew(pnl),
        "Worst month": pnl.min(),
        "Months": n,
    }


def deflated_sharpe(pnl, trial_sharpes):
    """Bailey and Lopez de Prado (2014). Probability that the true Sharpe is above zero,
    knowing we tried N versions (trial_sharpes = monthly Sharpes of every trial)."""
    n_trials = len(trial_sharpes)
    sr = pnl.mean() / pnl.std()                                # monthly Sharpe
    euler = 0.5772
    sr0 = np.std(trial_sharpes, ddof=1) * ((1 - euler) * norm.ppf(1 - 1 / n_trials)
                                           + euler * norm.ppf(1 - 1 / (n_trials * np.e)))
    g3, g4 = skew(pnl), kurtosis(pnl, fisher=False)
    z = (sr - sr0) * np.sqrt(len(pnl) - 1) / np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)
    return norm.cdf(z), sr0 * np.sqrt(12)


def pct(x):
    return f"{x:.1%}"


# ---------------------------------------------------------------- 4. main
if __name__ == "__main__":
    ind = load_industries()
    fac = load_factors()
    in_sample = ind.loc[:PUBLICATION]

    # every version I try goes into the trials log, good or bad (tested on 1927-1998 only)
    trials = []
    for lb in [3, 6, 9, 12]:
        for sk in [0, 1]:
            for n_legs in [5, 10, 15]:
                p, _ = run_strategy(in_sample, lb, sk, n_legs)
                s = stats(p)
                trials.append({"lookback": lb, "skip": sk, "n_legs": n_legs, "sharpe_1927_1998": round(s["Sharpe"], 3),
                               "t_stat": round(s["t-stat"], 2), "monthly_sharpe": p.mean() / p.std()})
    p, _ = run_strategy(in_sample)
    s = stats(vol_scaled(p))
    trials.append({"lookback": 12, "skip": 1, "n_legs": 10, "sharpe_1927_1998": round(s["Sharpe"], 3),
                   "t_stat": round(s["t-stat"], 2), "monthly_sharpe": s["Sharpe"] / np.sqrt(12),
                   "note": "vol-scaled"})
    trials = pd.DataFrame(trials)
    trials.drop(columns="monthly_sharpe").to_csv("results/trials_log.csv", index=False)

    # the pre-registered rule (12-1 months, top/bottom 10), full history
    pnl, weight = run_strategy(ind)
    pnl_is, pnl_oos = pnl.loc[:PUBLICATION], pnl.loc[PUBLICATION:].iloc[1:]
    paper = pnl.loc["1963-07":"1995-07"]                       # the sample of the 1999 paper
    dsr, lucky_sr = deflated_sharpe(pnl_is, trials["monthly_sharpe"])
    scaled = vol_scaled(pnl)
    dsr_scaled, _ = deflated_sharpe(scaled.loc[:PUBLICATION], trials["monthly_sharpe"])

    table = pd.DataFrame({"1927-1998 (in-sample)": stats(pnl_is), "1963-1995 (paper)": stats(paper),
                          "1999-2026 (out-of-sample)": stats(pnl_oos), "1927-2026 (full)": stats(pnl),
                          "Vol-scaled 1927-2026": stats(scaled)})
    print(table.round(3).to_string())
    print(f"\nTrials: {len(trials)} | Sharpe the best trial would show by luck: {lucky_sr:.2f}"
          f" | Deflated Sharpe 1927-1998: rule {dsr:.3f}, vol-scaled {dsr_scaled:.3f}")
    table.round(4).to_csv("results/summary.csv")
    pd.Series({"n_trials": len(trials), "lucky_sharpe": round(lucky_sr, 3), "dsr_1927_1998": round(dsr, 4),
               "dsr_vol_scaled_1927_1998": round(dsr_scaled, 4)}
              ).to_csv("results/dsr.csv", header=False)
    pnl.to_csv("results/monthly_pnl.csv", header=["pnl"], float_format="%.6f")
    turnover = weight.diff().abs().sum(axis=1).loc[pnl.index]
    print(f"Average turnover: {turnover.mean():.0%} of capital per month "
          f"(costs: {(turnover.mean() * COST + BORROW / 12) * 12:.2%} per year)")

    # is it just stock momentum in disguise? regression on the market and on the momentum factor
    both = pd.concat([pnl, fac[["Mkt-RF", "Mom"]]], axis=1, join="inner").dropna()
    rows = {}
    for name, x in [("Market only", ["Mkt-RF"]), ("Market + stock momentum (UMD)", ["Mkt-RF", "Mom"])]:
        reg = sm.OLS(both.iloc[:, 0], sm.add_constant(both[x])).fit(cov_type="HAC", cov_kwds={"maxlags": 6})
        rows[name] = {"alpha_per_year": reg.params["const"] * 12, "alpha_t": reg.tvalues["const"],
                      "beta_market": reg.params["Mkt-RF"], "beta_umd": reg.params.get("Mom", np.nan),
                      "r2": reg.rsquared}
    reg_table = pd.DataFrame(rows).T
    print("\n", reg_table.round(3).to_string())
    reg_table.round(4).to_csv("results/regression.csv")

    # momentum crashes: the worst months and the two famous episodes
    worst = pnl.nsmallest(5)
    crashes = pd.DataFrame({
        "Industry momentum": [(1 + pnl.loc[a:b]).prod() - 1 for a, b in [("1932-06", "1932-08"), ("2009-03", "2009-05")]],
        "Vol-scaled": [(1 + scaled.loc[a:b]).prod() - 1 for a, b in [("1932-06", "1932-08"), ("2009-03", "2009-05")]],
        "US market": [(1 + fac["Mkt-RF"] + fac["RF"]).loc[a:b].prod() - 1 for a, b in [("1932-06", "1932-08"),
                                                                                       ("2009-03", "2009-05")]]},
        index=["Jun-Aug 1932", "Mar-May 2009"])
    print("\nWorst months:\n", worst.round(3).to_string(), "\n\nCrashes:\n", crashes.round(3).to_string())
    crashes.round(4).to_csv("results/crashes.csv")

    # bridge to the live book: the same rule on the 11 sector ETFs, top 3 / bottom 3
    etf = load_etfs()
    pnl_etf, _ = run_strategy(etf, n_legs=3)
    pnl_etf = pnl_etf.loc["2000-01":]
    same = pd.concat([pnl.rename("49 industries"), pnl_etf.rename("11 ETFs")], axis=1, join="inner")
    etf_table = pd.DataFrame({"49 industries (same months)": stats(same.iloc[:, 0]), "11 sector ETFs": stats(pnl_etf)})
    print("\nSector ETFs vs 49 industries:\n", etf_table.round(3).to_string(),
          f"\nCorrelation: {same.corr().iloc[0, 1]:.2f}")
    etf_table.loc["Correlation"] = same.corr().iloc[0, 1]
    etf_table.round(4).to_csv("results/etf_vs_industries.csv")
    pnl_etf.to_csv("results/monthly_pnl_etf.csv", header=["pnl"], float_format="%.6f")

    # ------------------------------------------------------------ charts
    mkt = (fac["Mkt-RF"] + fac["RF"]).loc[pnl.index]
    plt.figure(figsize=(10, 5))
    (1 + pnl).cumprod().plot(label="Industry momentum, long/short (after costs)", lw=2)
    (1 + scaled).cumprod().plot(label="Vol-scaled version", alpha=0.7)
    (1 + mkt).cumprod().plot(label="US stock market", color="grey", alpha=0.6)
    plt.axvspan(pd.Timestamp(PUBLICATION), pnl.index[-1], color="grey", alpha=0.15, label="After publication")
    plt.yscale("log"); plt.legend(); plt.title("Growth of 1 USD, 1927-2026"); plt.tight_layout()
    plt.savefig("results/1_equity_curve.png", dpi=120); plt.close()

    plt.figure(figsize=(9, 4))
    pivot = trials[trials.get("note").isna()].pivot_table(index="lookback", columns=["skip", "n_legs"],
                                                          values="sharpe_1927_1998")
    pivot.plot.bar(ax=plt.gca(), width=0.85)
    plt.ylabel("Sharpe 1927-1998"); plt.title(f"The {len(trials)} trials (legend: skip, industries per leg)")
    plt.legend(fontsize=7, ncol=2); plt.tight_layout(); plt.savefig("results/2_trials.png", dpi=120); plt.close()

    roll = pnl.rolling(120).mean() / pnl.rolling(120).std() * np.sqrt(12)
    plt.figure(figsize=(10, 4))
    roll.plot(lw=2, label="10-year rolling Sharpe")
    plt.axhline(0, color="black", lw=0.8); plt.axvline(pd.Timestamp(PUBLICATION), color="red", ls="--", label="Publication")
    plt.legend(); plt.title("Does the effect fade once it is known?"); plt.tight_layout()
    plt.savefig("results/3_rolling_sharpe.png", dpi=120); plt.close()

    plt.figure(figsize=(10, 4))
    (1 + same).cumprod().plot(ax=plt.gca(), lw=2)
    plt.title(f"Same rule, two universes, 2000-2026 (correlation {same.corr().iloc[0, 1]:.2f})")
    plt.tight_layout(); plt.savefig("results/4_etf_vs_industries.png", dpi=120); plt.close()
