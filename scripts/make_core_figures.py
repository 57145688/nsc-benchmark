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


def pin_map(hot, path):
    grid = np.array(hot["pin_power"]["relative"], dtype=float)
    params = json.load(open(PARAMS))
    nonfuel = {tuple(item) for item in params["assembly"]["nonfuel_positions"]}
    masked = np.ma.masked_less_equal(grid, 0.0)
    figure, ax = plt.subplots(figsize=(6.4, 5.6), constrained_layout=True)
    cmap = plt.get_cmap("magma").copy()
    cmap.set_bad("#1b222b")
    image = ax.imshow(
        masked,
        origin="lower",
        cmap=cmap,
        vmin=0.7,
        vmax=1.3,
        extent=(0.5, grid.shape[0] + 0.5, 0.5, grid.shape[1] + 0.5),
    )
    for column, row in nonfuel:
        ax.plot(column + 1, row + 1, "x", color="white", markersize=7, mew=2)
    ax.set_xlabel("pin column")
    ax.set_ylabel("pin row")
    ax.set_title(
        "centre assembly (2.4% U-235): pin power / fuel-pin mean\n"
        "white x = guide tube or instrument tube",
        fontsize=10,
    )
    colour = figure.colorbar(image, ax=ax, pad=0.02)
    colour.set_label("pin power / assembly mean")
    figure.savefig(path, dpi=150)
    plt.close(figure)


def axial_profile(hot, path):
    z = np.array(hot["axial_power"]["z_cm"])
    power = np.array(hot["axial_power"]["relative"])
    flux = np.array(hot["axial_power"]["flux_relative"])
    figure, ax = plt.subplots(figsize=(6.4, 4.6), constrained_layout=True)
    ax.plot(z, power, lw=2, color="#e4572e", label="fission heating")
    ax.plot(z, flux, lw=1.4, ls="--", color="#4361ee", label="flux")
    ax.set_xlabel("z / cm")
    ax.set_ylabel("relative to axial mean")
    ax.set_title("axial profile (reflective ends: no axial leakage)")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False)
    ax.set_ylim(0.95, 1.09)
    ax.text(
        0.03,
        0.94,
        "flat within +/-3%: the 2D core has no axial leakage,\n"
        "the remaining wiggle is Monte Carlo noise",
        transform=ax.transAxes,
        fontsize=9,
        color="#333333",
        va="top",
    )
    figure.savefig(path, dpi=150)
    plt.close(figure)


def spectrum(hot, path):
    edges = np.array(hot["spectrum"]["energy_edges_eV"])
    centres = np.sqrt(edges[:-1] * edges[1:])
    widths = np.diff(edges)
    fuel = np.array(hot["spectrum"]["fuel_flux"])
    water = np.array(hot["spectrum"]["water_flux"])
    fuel = fuel / fuel.sum() / widths
    water = water / water.sum() / widths

    figure, ax = plt.subplots(figsize=(6.6, 4.8), constrained_layout=True)
    ax.loglog(centres, centres * fuel, lw=2, color="#e4572e", label="fuel pin")
    ax.loglog(centres, centres * water, lw=2, color="#4361ee", label="pin-cell water")
    ax.axvline(0.625, color="#9aa5b1", lw=1, ls=":")
    ax.set_xlabel("energy / eV")
    ax.set_ylabel("E phi(E) per unit lethargy (normalised)")
    thermal = hot["spectrum"]["fuel"]
    ax.set_title(
        "neutron spectrum: fuel thermal {:.1f}%, fast {:.1f}%".format(
            100 * thermal["thermal_fraction"], 100 * thermal["fast_fraction"]
        ),
        fontsize=10,
    )
    ax.grid(alpha=0.3, which="both")
    ax.legend(frameon=False)
    figure.savefig(path, dpi=150)
    plt.close(figure)


def convergence(hot, path):
    k = np.array(hot["k_batches"])
    generations = np.arange(1, len(k) + 1)
    running = np.cumsum(k) / generations
    nuclides = hot["nuclides"]

    figure, (left, right) = plt.subplots(
        1, 2, figsize=(11, 4.2), constrained_layout=True
    )
    left.plot(generations, k, ".", color="#8fb8de", ms=3, label="batch k")
    left.plot(generations, running, color="#e4572e", lw=1.6, label="running mean")
    left.axvline(hot["inactive"], color="#9aa5b1", ls=":", lw=1)
    left.set_xlabel("batch")
    left.set_ylabel("k")
    left.set_title(f"eigenvalue history (k = {hot['k_eff']:.5f})")
    left.grid(alpha=0.3)
    left.legend(frameon=False, fontsize=8)

    labels = ["U-235 fission", "U-238 fission", "U-235 absorption", "U-238 absorption"]
    values = [
        nuclides["U235_fission"],
        nuclides["U238_fission"],
        nuclides["U235_absorption"],
        nuclides["U238_absorption"],
    ]
    bars = right.bar(range(4), values, color=["#e4572e", "#f4a261", "#4361ee", "#8fb8de"])
    right.set_xticks(range(4))
    right.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    right.set_ylabel("reaction rate per source neutron")
    right.set_title("nuclide reaction rates")
    right.grid(axis="y", alpha=0.3)
    for bar, value in zip(bars, values):
        right.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:.3f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main():
    cold = load(COLD)
    hot = load(HOT)
    power_maps(cold, hot, os.path.join(OUT, "openmc_core_power.png"))
    keff_and_rings(cold, hot, os.path.join(OUT, "openmc_keff_rings.png"))
    pin_map(hot, os.path.join(OUT, "openmc_pin_power.png"))
    axial_profile(hot, os.path.join(OUT, "openmc_axial.png"))
    spectrum(hot, os.path.join(OUT, "openmc_spectrum.png"))
    convergence(hot, os.path.join(OUT, "openmc_convergence.png"))
    print("wrote 6 OpenMC figures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
