"""Run the boron concentration sweep for the NuScale pin cell.

Writes ``results/boron_sweep.json`` with k_inf, its standard deviation, the
reactivity worth of boron and the interpolated critical boron concentration.

    python -m scripts.sweep_boron [--force]
"""

import argparse
import glob
import json
import os
import sys

import numpy as np
import openmc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nsc_bench.model import build_model, load_params  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
CASES = os.path.join(RESULTS, "cases")


def latest_statepoint(case_dir):
    files = sorted(glob.glob(os.path.join(case_dir, "statepoint*.h5")))
    return files[-1] if files else None


def run_point(boron_ppm, params, force=False):
    case_dir = os.path.join(CASES, f"b{boron_ppm:04d}")
    os.makedirs(case_dir, exist_ok=True)
    statepoint = latest_statepoint(case_dir)

    if force or statepoint is None:
        model = build_model(boron_ppm, params)
        openmc.config["cross_sections"] = os.environ["OPENMC_CROSS_SECTIONS"]
        statepoint = model.run(cwd=case_dir, threads=params["threads"])
        statepoint = statepoint or latest_statepoint(case_dir)

    with openmc.StatePoint(statepoint) as sp:
        return float(sp.keff.nominal_value), float(sp.keff.std_dev)


def critical_boron(points):
    """Linear interpolation of the boron concentration where k_inf crosses 1."""
    for low, high in zip(points, points[1:]):
        if low["k_inf"] >= 1.0 >= high["k_inf"]:
            fraction = (low["k_inf"] - 1.0) / (low["k_inf"] - high["k_inf"])
            return low["boron_ppm"] + fraction * (high["boron_ppm"] - low["boron_ppm"])
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="rerun existing cases")
    args = parser.parse_args()

    params = load_params()
    points = []
    for boron_ppm in params["boron_ppm"]:
        k_inf, k_std = run_point(boron_ppm, params, force=args.force)
        points.append({"boron_ppm": boron_ppm, "k_inf": k_inf, "k_std": k_std})
        print(f"{boron_ppm:6d} ppm   k_inf = {k_inf:.5f} +/- {k_std:.5f}", flush=True)

    boron = np.array([p["boron_ppm"] for p in points], dtype=float)
    k = np.array([p["k_inf"] for p in points])
    reactivity = 1.0 - 1.0 / k
    slope_k = np.polyfit(boron, k, 1)[0]
    slope_rho = np.polyfit(boron, reactivity, 1)[0]
    critical = critical_boron(points)

    reference_boron = 1200.0
    summary = {
        "model": params["description"],
        "temperature_K": params["temperature_K"],
        "enrichment_wt_pct": params["u235_enrichment_wt_pct"],
        "particles": params["particles"],
        "batches": params["batches"],
        "inactive_batches": params["inactive_batches"],
        "boron_sweep": points,
        "d_k_inf_per_ppm_pcm": float(-slope_k * 1e5),
        "boron_worth_pcm_per_ppm": float(-slope_rho * 1e5),
        "k_inf_at_reference_boron": {
            "boron_ppm": reference_boron,
            "k_inf": float(np.interp(reference_boron, boron, k)),
        },
        "critical_boron_ppm": None if critical is None else float(critical),
        "k_inf_at_zero_boron": points[0]["k_inf"] if points[0]["boron_ppm"] == 0 else None,
    }

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "boron_sweep.json"), "w") as handle:
        json.dump(summary, handle, indent=2)

    print(f"\nboron worth = {summary['boron_worth_pcm_per_ppm']:.2f} pcm/ppm")
    if critical is not None:
        print(f"critical boron = {critical:.0f} ppm")
    else:
        print("critical boron not reached inside the swept range")
    print("wrote results/boron_sweep.json")


if __name__ == "__main__":
    main()
