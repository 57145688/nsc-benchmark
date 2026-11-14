"""Plots for the OpenMC core calculations.

    python scripts/make_core_figures.py

Compares the first core calculation (initial water density) with the hot-state
calculation driven by the CFD ring densities.  All labels are English because
the default matplotlib fonts have no CJK glyphs.
"""

import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "results", "figures")
PARAMS = os.path.join(HERE, "params", "nuscale_core.json")
COLD = os.path.join(HERE, "results", "coupling", "iter0", "power.json")
HOT = os.path.join(HERE, "results", "coupling", "hx_hot", "power.json")

SIZE = 7


def load(path):
    with open(path) as handle:
        return json.load(handle)


def layout(data):
    """Return {(column, row): (power fraction, enrichment)} and k_eff."""
    cells = {}
    fractions = []
    for assembly in data["assemblies"]:
        fraction = float(assembly["power_fraction"])
        cells[(assembly["column"], assembly["row"])] = (
            fraction,
            float(assembly["enrichment_wt_pct"]),
            int(assembly["ring"]),
        )
        fractions.append(fraction)
    factor = np.array(fractions) * len(fractions)
    return cells, factor


def draw_map(ax, cells, factor_max, title):
    grid = np.full((SIZE, SIZE), np.nan)
    for (column, row), (fraction, _, _) in cells.items():
        grid[row - 1, column - 1] = fraction * len(cells)
    image = ax.imshow(
        grid,
        origin="lower",
        cmap="magma",
        vmin=0.0,
        vmax=factor_max,
        extent=(0.5, SIZE + 0.5, 0.5, SIZE + 0.5),
    )
    for (column, row), (fraction, enrichment, _) in cells.items():
        shade = "white" if fraction * len(cells) < 0.75 * factor_max else "black"
        ax.text(
            column,
            row + 0.22,
            f"{fraction * len(cells):.2f}",
            color=shade,
            fontsize=9,
            ha="center",
            va="center",
        )
        ax.text(
            column,
            row - 0.24,
            f"{enrichment:.1f}%",
            color=shade,
            fontsize=7,
            ha="center",
            va="center",
            alpha=0.85,
        )
    ax.set_xlim(0.5, SIZE + 0.5)
    ax.set_ylim(0.5, SIZE + 0.5)
    ax.set_xticks(range(1, SIZE + 1))
    ax.set_yticks(range(1, SIZE + 1))
    ax.set_xticklabels([])
    ax.set_yticklabels([])
    ax.tick_params(length=0)
    ax.set_facecolor("#101418")
    ax.set_title(title, fontsize=11)
    for spine in ax.spines.values():
        spine.set_color("#44515f")
    return image


def power_maps(cold, hot, path):
    cold_cells, cold_factor = layout(cold)
    hot_cells, hot_factor = layout(hot)
    factor_max = max(cold_factor.max(), hot_factor.max()) * 1.05

    figure, (left, right) = plt.subplots(1, 2, figsize=(11, 5.2), constrained_layout=True)
    image = draw_map(
        left,
        cold_cells,
        factor_max,
        f"initial water density  k = {cold['k_eff']:.5f}",
    )
    draw_map(
        right,
        hot_cells,
        factor_max,
        f"hot feedback  k = {hot['k_eff']:.5f}",
    )
    for ax in (left, right):
        ax.set_xlabel("assembly column")
        ax.set_ylabel("assembly row")
    colour = figure.colorbar(image, ax=[left, right], pad=0.02, shrink=0.9)
    colour.set_label("assembly power / core mean")
    figure.suptitle(
        "37-assembly 2D core: power fraction and enrichment (bottom label)", fontsize=12
    )
    figure.savefig(path, dpi=150)
    plt.close(figure)


def keff_and_rings(cold, hot, path):
    figure, (left, right) = plt.subplots(
        1, 2, figsize=(11, 4.4), constrained_layout=True
    )
    values = [cold["k_eff"], hot["k_eff"]]
    errors = [cold["k_sigma"], hot["k_sigma"]]
    labels = ["initial density\n0.998 g/cm3", "hot feedback\n0.72-0.78 g/cm3"]
    bars = left.bar(range(2), values, yerr=errors, capsize=6, color=["#4361ee", "#e4572e"])
    left.set_xticks(range(2))
    left.set_xticklabels(labels, fontsize=9)
    left.set_ylim(1.19, 1.26)
    left.set_ylabel("k_eff")
    left.set_title("core eigenvalues")
    left.grid(axis="y", alpha=0.3)
    for bar, value, error in zip(bars, values, errors):
        left.text(
            bar.get_x() + bar.get_width() / 2,
            value + error + 0.003,
            f"{value:.5f}",
            ha="center",
            fontsize=9,
        )
    left.annotate(
        f"delta k = {values[0] - values[1]:.4f}",
        xy=(0.5, 1.245),
        xycoords=("data", "data"),
        ha="center",
        fontsize=10,
        color="#333333",
    )

    rings = range(1, SIZE // 2 + 2)
    cold_rings = [
        sum(cell[0] for cell in layout(cold)[0].values() if cell[2] == ring)
        for ring in rings
    ]
    hot_rings = [
        sum(cell[0] for cell in layout(hot)[0].values() if cell[2] == ring)
        for ring in rings
    ]
    width = 0.38
    positions = np.arange(len(list(rings)))
    right.bar(positions - width / 2, cold_rings, width, label="initial", color="#4361ee")
    right.bar(positions + width / 2, hot_rings, width, label="hot", color="#e4572e")
    right.set_xticks(positions)
    right.set_xticklabels([f"ring {ring}" for ring in rings])
    right.set_ylabel("share of core power")
    right.set_title("radial power distribution")
    right.grid(axis="y", alpha=0.3)
    right.legend(frameon=False)
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main():
    cold = load(COLD)
    hot = load(HOT)
    power_maps(cold, hot, os.path.join(OUT, "openmc_core_power.png"))
    keff_and_rings(cold, hot, os.path.join(OUT, "openmc_keff_rings.png"))
    print("wrote openmc_core_power.png, openmc_keff_rings.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
