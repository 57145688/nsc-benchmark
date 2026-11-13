"""Plot k_inf against the boron concentration from results/boron_sweep.json."""

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")

with open(os.path.join(RESULTS, "boron_sweep.json")) as handle:
    data = json.load(handle)

boron = np.array([p["boron_ppm"] for p in data["boron_sweep"]], dtype=float)
k = np.array([p["k_inf"] for p in data["boron_sweep"]])
k_std = np.array([p["k_std"] for p in data["boron_sweep"]])

fig, ax = plt.subplots(figsize=(7.2, 4.6), facecolor="white")
ax.axhline(1.0, color="#c0392b", lw=1.0, ls="--", label="critical (k$_{inf}$ = 1)")
ax.errorbar(
    boron,
    k,
    yerr=k_std * 2,
    fmt="o-",
    color="#1f5fa8",
    lw=1.8,
    ms=6,
    capsize=3,
    label="OpenMC pin cell",
)

critical = data.get("critical_boron_ppm")
if critical is not None:
    ax.axvline(critical, color="#2a9d8f", lw=1.2, ls=":")
    ax.annotate(
        f"critical = {critical:.0f} ppm",
        xy=(critical, 1.0),
        xytext=(critical + 60, 1.0 + 0.35 * (k.max() - k.min())),
        color="#2a9d8f",
        fontsize=9,
        arrowprops=dict(arrowstyle="->", color="#2a9d8f", lw=1.0),
    )

ax.set_xlabel("boron concentration in the moderator [ppm]")
ax.set_ylabel("k$_{inf}$")
ax.set_title(
    "NuScale 17x17 pin cell, "
    f"{data['enrichment_wt_pct']:.2f} wt% U-235, {data['temperature_K']:.0f} K"
)
ax.grid(alpha=0.3)
ax.legend(loc="upper right", fontsize=9)
plt.tight_layout()

for suffix in ("png", "svg"):
    path = os.path.join(RESULTS, f"kinf_vs_boron.{suffix}")
    plt.savefig(path, dpi=170)
    print("saved", path)
