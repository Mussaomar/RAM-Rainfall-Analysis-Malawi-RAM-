"""
Climate indices computed from a monthly rainfall series.

Every function here takes a plain pandas.Series indexed by a monthly
PeriodIndex (or DataFrame with 'date'/'rainfall_mm' columns, converted
internally) and returns index values -- it does not care whether the
series came from CHIRPS-via-GEE or a user-supplied ground-station CSV,
so the same code path drives both, and the two sources are directly
comparable once loaded.
"""

import numpy as np
import pandas as pd
from scipy import stats


def _to_monthly_series(df_or_series, date_col="date", value_col="rainfall_mm"):
    if isinstance(df_or_series, pd.Series):
        s = df_or_series.copy()
    else:
        df = df_or_series.copy()
        df[date_col] = pd.to_datetime(df[date_col])
        s = df.set_index(date_col)[value_col]
    s.index = pd.to_datetime(s.index).to_period("M")
    return s.sort_index()


def load_ground_station_csv(path, date_col="date", value_col="rainfall_mm"):
    """
    Read a user-supplied monthly rainfall CSV for comparison against
    CHIRPS. Expects at minimum a date column (YYYY-MM or YYYY-MM-DD)
    and a rainfall column; column names are configurable since gauge
    records rarely arrive in one standard layout.
    """
    df = pd.read_csv(path)
    missing = {date_col, value_col} - set(df.columns)
    if missing:
        raise ValueError(
            f"CSV is missing expected column(s) {missing}. "
            f"Found columns: {list(df.columns)}"
        )
    return _to_monthly_series(df, date_col, value_col)


# ---------------------------------------------------------------- SPI ----

def compute_spi(monthly_series, scale=3, dist="gamma"):
    """
    Standardized Precipitation Index (McKee et al., 1993).

    monthly_series: pandas.Series of monthly rainfall (mm), monthly
        PeriodIndex, gap-free within the period of interest.
    scale: accumulation window in months (1, 3, 6, 12, 24 are typical).

    Method: rolling `scale`-month sums are fit, per calendar month
    (i.e. all rolling Januaries fit together, all Februaries together,
    etc.) to a 2-parameter gamma distribution, and each observation is
    converted to its cumulative probability under that fitted gamma
    then to a standard-normal z-score via the inverse normal CDF. Zero
    rainfall is handled with the standard mixed-distribution
    correction (q = fraction of zero months; CDF = q + (1-q)*gammaCDF).

    Returns a pandas.Series of SPI values aligned to monthly_series's
    index (the first scale-1 months are NaN, since a rolling sum needs
    scale months of history).
    """
    s = monthly_series.astype(float)
    accum = s.rolling(window=scale, min_periods=scale).sum()

    spi = pd.Series(index=accum.index, dtype=float)
    for month in range(1, 13):
        mask = accum.index.month == month
        vals = accum[mask].dropna()
        if len(vals) < 4:
            continue  # not enough history to fit a distribution reliably
        zero_frac = (vals == 0).mean()
        nonzero = vals[vals > 0]
        if len(nonzero) >= 3:
            shape, loc, scale_param = stats.gamma.fit(nonzero, floc=0)
            cdf = zero_frac + (1 - zero_frac) * stats.gamma.cdf(
                vals, shape, loc=loc, scale=scale_param
            )
        else:
            cdf = stats.rankdata(vals) / (len(vals) + 1)
        cdf = np.clip(cdf, 1e-6, 1 - 1e-6)
        spi.loc[vals.index] = stats.norm.ppf(cdf)

    return spi


SPI_CLASSES = [
    (2.0, np.inf, "Extremely wet"),
    (1.5, 2.0, "Very wet"),
    (1.0, 1.5, "Moderately wet"),
    (-1.0, 1.0, "Near normal"),
    (-1.5, -1.0, "Moderately dry"),
    (-2.0, -1.5, "Severely dry"),
    (-np.inf, -2.0, "Extremely dry"),
]


def classify_spi(value):
    if pd.isna(value):
        return None
    for low, high, label in SPI_CLASSES:
        if low <= value < high:
            return label
    return None


# ---------------------------------------------------------------- RAI ----

def compute_rai(annual_series):
    """
    Rainfall Anomaly Index (Van Rooy, 1965).

    annual_series: pandas.Series of annual (or seasonal) rainfall
        totals, one value per year.

    Positive anomalies: RAI = 3 * (P - Pmean) / (mean of 10 highest
        years - Pmean)
    Negative anomalies: RAI = -3 * (P - Pmean) / (mean of 10 lowest
        years - Pmean)

    With fewer than 10 years of record the highest/lowest-decile means
    fall back to the top/bottom third of available years, which is
    noted in the returned metadata dict rather than silently applied.
    """
    s = annual_series.astype(float).dropna()
    n = len(s)
    k = min(10, max(1, n // 3)) if n < 10 else 10
    mean_p = s.mean()
    highest_mean = s.nlargest(k).mean()
    lowest_mean = s.nsmallest(k).mean()

    rai = pd.Series(index=s.index, dtype=float)
    for year, p in s.items():
        if p >= mean_p:
            rai.loc[year] = 3 * (p - mean_p) / (highest_mean - mean_p)
        else:
            rai.loc[year] = -3 * (p - mean_p) / (lowest_mean - mean_p)

    meta = {"n_years": n, "k_used": k, "used_fallback_k": n < 10}
    return rai, meta


# ---------------------------------------------------------------- PCI ----

def compute_pci(monthly_series):
    """
    Precipitation Concentration Index (Oliver, 1980), computed per
    calendar year: PCI = 100 * sum(Pi^2) / (sum(Pi))^2, over the 12
    monthly totals Pi of that year.

    Years with fewer than 12 months present are skipped rather than
    computed on a partial year, since PCI on <12 months is not
    comparable to the standard annual index.

    Returns a pandas.Series of PCI values indexed by year, plus a
    parallel classification per Oliver (1980):
        <10  uniform distribution
        10-15 moderate concentration
        15-20 irregular distribution
        >20  strong concentration (erosive risk)
    """
    df = monthly_series.to_frame("mm")
    df["year"] = df.index.year
    pci = {}
    for year, group in df.groupby("year"):
        if len(group) < 12:
            continue
        p = group["mm"].values
        pci[year] = 100 * np.sum(p ** 2) / (np.sum(p) ** 2)
    pci_series = pd.Series(pci).sort_index()

    def classify(v):
        if v < 10:
            return "Uniform"
        elif v < 15:
            return "Moderate concentration"
        elif v < 20:
            return "Irregular distribution"
        else:
            return "Strong concentration"

    classes = pci_series.apply(classify)
    return pci_series, classes
