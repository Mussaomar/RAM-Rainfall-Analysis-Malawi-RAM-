"""
Chart generation. Kept separate from the analysis math so the plugin
UI can call these directly and drop a PNG/SVG/PDF onto disk, or embed
the returned Figure in a Qt widget via FigureCanvasQTAgg.
"""

import matplotlib
matplotlib.use("Agg")  # safe default for headless export; the UI layer
# swaps in the Qt5Agg backend before embedding a canvas in a dialog.
import matplotlib.pyplot as plt
import numpy as np


def _save_or_return(fig, out_path=None):
    if out_path:
        fig.savefig(out_path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        return out_path
    return fig


def plot_time_series(series, title, ylabel="Rainfall (mm)", out_path=None):
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(series.index.astype(str), series.values, color="#1f6feb", linewidth=1.5)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return _save_or_return(fig, out_path)


def plot_monthly_climatology(monthly_series, title="Monthly Rainfall Climatology", out_path=None):
    """Boxplot of rainfall for each calendar month across all years in the series."""
    df = monthly_series.to_frame("mm")
    df["month"] = df.index.month
    data = [df.loc[df["month"] == m, "mm"].values for m in range(1, 13)]

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.boxplot(data, labels=[
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ])
    ax.set_title(title)
    ax.set_ylabel("Rainfall (mm)")
    fig.tight_layout()
    return _save_or_return(fig, out_path)


def plot_spi(spi_series, title="SPI", out_path=None):
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(spi_series))
    colors = ["#c0392b" if v < 0 else "#2471a3" for v in spi_series.values]
    ax.bar(x, spi_series.values, color=colors, width=1.0)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x[::max(1, len(x) // 15)])
    ax.set_xticklabels(
        [str(spi_series.index[i]) for i in x[::max(1, len(x) // 15)]], rotation=45
    )
    ax.set_title(title)
    ax.set_ylabel("SPI")
    fig.tight_layout()
    return _save_or_return(fig, out_path)


def plot_rai(rai_series, title="Rainfall Anomaly Index (RAI)", out_path=None):
    fig, ax = plt.subplots(figsize=(9, 4))
    colors = ["#c0392b" if v < 0 else "#2471a3" for v in rai_series.values]
    ax.bar(rai_series.index.astype(str), rai_series.values, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title(title)
    ax.set_ylabel("RAI")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return _save_or_return(fig, out_path)


def plot_pci(pci_series, title="Precipitation Concentration Index (PCI)", out_path=None):
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(pci_series.index.astype(str), pci_series.values, marker="o", color="#8e44ad")
    for threshold, label in [(10, "Uniform/Moderate"), (15, "Moderate/Irregular"), (20, "Irregular/Strong")]:
        ax.axhline(threshold, color="gray", linestyle="--", linewidth=0.7)
    ax.set_title(title)
    ax.set_ylabel("PCI")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return _save_or_return(fig, out_path)


def plot_trend(series, sen_slope, sen_intercept, title="Rainfall Trend", ylabel="Rainfall (mm)", out_path=None):
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(series))
    ax.scatter(series.index.astype(str), series.values, color="#1f6feb", s=20, label="Observed")
    trend_line = sen_intercept + sen_slope * x
    ax.plot(series.index.astype(str), trend_line, color="#c0392b", linewidth=2,
            label=f"Sen's slope = {sen_slope:.2f}/yr")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=45)
    ax.legend()
    fig.tight_layout()
    return _save_or_return(fig, out_path)


def plot_ground_vs_chirps(chirps_series, ground_series, title="CHIRPS vs Ground Station", out_path=None):
    """Side-by-side comparison for the CSV ground-station import path."""
    fig, ax = plt.subplots(figsize=(9, 4))
    common_index = chirps_series.index.union(ground_series.index)
    ax.plot(common_index.astype(str), chirps_series.reindex(common_index).values,
            label="CHIRPS", color="#1f6feb")
    ax.plot(common_index.astype(str), ground_series.reindex(common_index).values,
            label="Ground station", color="#e67e22", linestyle="--")
    ax.set_title(title)
    ax.set_ylabel("Rainfall (mm)")
    ax.tick_params(axis="x", rotation=45)
    ax.legend()
    fig.tight_layout()
    return _save_or_return(fig, out_path)
