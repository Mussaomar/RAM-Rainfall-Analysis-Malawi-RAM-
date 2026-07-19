"""
Trend analysis on an annual (or otherwise regularly-spaced) rainfall
or index series. Implemented directly with numpy/scipy rather than
pulling in pymannkendall, so the plugin has one fewer external
dependency to fail to install inside the QGIS Python environment.
"""

import numpy as np
import pandas as pd
from scipy import stats


def mann_kendall_test(series, alpha=0.05):
    """
    Original (non-seasonal) Mann-Kendall trend test.

    series: pandas.Series, index order defines the time order (sort
        before calling if the index isn't already chronological).

    Returns a dict: {trend, h, p, z, s, var_s, tau} where:
        trend: 'increasing', 'decreasing', or 'no trend'
        h: True if trend is significant at the given alpha
        p: two-sided p-value
        z: standard normal test statistic
        s: Mann-Kendall S statistic
        tau: Kendall's tau (rank correlation)

    Ties in the data are handled with the standard variance
    correction (Kendall, 1975) rather than ignored.
    """
    x = series.dropna().values.astype(float)
    n = len(x)
    if n < 4:
        raise ValueError("Mann-Kendall test needs at least 4 non-missing observations")

    s = 0
    for k in range(n - 1):
        s += np.sum(np.sign(x[k + 1:] - x[k]))

    unique, counts = np.unique(x, return_counts=True)
    tie_term = np.sum(counts * (counts - 1) * (2 * counts + 5))
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0

    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0

    p = 2 * (1 - stats.norm.cdf(abs(z)))
    h = p < alpha
    trend = "no trend"
    if h:
        trend = "increasing" if z > 0 else "decreasing"

    tau = s / (0.5 * n * (n - 1))

    return {
        "trend": trend, "h": bool(h), "p": float(p), "z": float(z),
        "s": int(s), "var_s": float(var_s), "tau": float(tau), "n": n,
    }


def sens_slope(series):
    """
    Theil-Sen (Sen's) slope estimator: the median of all pairwise
    slopes (xj - xi) / (j - i) for j > i. Robust to outliers, which
    is why it is paired with Mann-Kendall rather than OLS slope for
    the significance test.

    series: pandas.Series with a chronologically-ordered index; the
        returned slope is in series-units per index-step (e.g. mm/year
        if series is annual rainfall indexed by year).

    Returns (slope, intercept) where intercept is chosen so the Sen
    line passes through the median of (index, value).
    """
    x = np.arange(len(series))
    y = series.values.astype(float)
    valid = ~np.isnan(y)
    x, y = x[valid], y[valid]
    n = len(x)
    if n < 2:
        raise ValueError("Sen's slope needs at least 2 non-missing observations")

    slopes = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            slopes.append((y[j] - y[i]) / (x[j] - x[i]))
    slope = np.median(slopes)
    intercept = np.median(y) - slope * np.median(x)
    return float(slope), float(intercept)


def linear_regression(series):
    """
    Ordinary least-squares trend line, for comparison against the
    more robust Sen's slope above.

    Returns dict: {slope, intercept, r_squared, p_value, std_err}.
    """
    x = np.arange(len(series))
    y = series.values.astype(float)
    valid = ~np.isnan(y)
    x, y = x[valid], y[valid]

    result = stats.linregress(x, y)
    return {
        "slope": float(result.slope),
        "intercept": float(result.intercept),
        "r_squared": float(result.rvalue ** 2),
        "p_value": float(result.pvalue),
        "std_err": float(result.stderr),
    }


def moving_average(series, window):
    """Simple centered moving average, window in number of periods (e.g. 3/5/10 years)."""
    return series.rolling(window=window, center=True, min_periods=1).mean()


def period_comparison(series, breakpoints):
    """
    Compare mean values across custom time slices, e.g. decades.

    breakpoints: list of (label, start, end) tuples, start/end being
        values comparable to series.index (inclusive on both ends).

    Returns a pandas.DataFrame with columns
        ['period', 'mean', 'std', 'n', 'pct_change_from_first'].
    """
    rows = []
    first_mean = None
    for label, start, end in breakpoints:
        subset = series[(series.index >= start) & (series.index <= end)].dropna()
        mean_val = subset.mean() if len(subset) else np.nan
        if first_mean is None and not np.isnan(mean_val):
            first_mean = mean_val
        pct_change = (
            100 * (mean_val - first_mean) / first_mean
            if first_mean not in (None, 0) and not np.isnan(mean_val)
            else np.nan
        )
        rows.append({
            "period": label, "mean": mean_val, "std": subset.std(),
            "n": len(subset), "pct_change_from_first": pct_change,
        })
    return pd.DataFrame(rows)
