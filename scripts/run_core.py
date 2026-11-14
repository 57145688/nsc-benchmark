"""Run the 37-assembly OpenMC core and write the power distribution.

Outputs ``results/core/power.json`` which is the input to the OpenFOAM case
builder.  Densities can be supplied from a previous CFD iteration so that the
same script drives the feedback loop.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openmc  # noqa: E402

from nsc_bench import core  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Radial boundaries (cm) used to map assemblies onto CFD rings.
RINGS_CM = [15.0, 35.0, 55.0, 85.0]


def ring_of(radius_cm):
    for index, limit in enumerate(RINGS_CM, start=1):
        if radius_cm <= limit:
            return index
    return len(RINGS_CM)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--particles", type=int, default=10000)
    parser.add_argument("--batches", type=int, default=120)
    parser.add_argument("--inactive", type=int, default=30)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--densities", help="JSON with assembly density feedback")
    parser.add_argument("--out", default=os.path.join(HERE, "results", "core"))
    args = parser.parse_args(argv)

    params = core.load_params()
    densities = {}
    if args.densities:
        with open(args.densities) as handle:
            payload = json.load(handle)
        for key, value in payload.get("assemblies", {}).items():
            column, row = key.split(",")
            densities[(int(column), int(row))] = float(value)
        if "downcomer" in payload:
            densities["downcomer"] = float(payload["downcomer"])

    model, mesh, _ = core.build_model(
        params,
        densities=densities,
        particles=args.particles,
        batches=args.batches,
        inactive=args.inactive,
    )

    os.makedirs(args.out, exist_ok=True)
    model.export_to_xml(args.out)
    openmc.run(cwd=args.out, threads=args.threads, output=True)

    statepoint_file = os.path.join(args.out, f"statepoint.{args.batches}.h5")
    statepoint = openmc.StatePoint(statepoint_file)
    tally = statepoint.get_tally(name="assembly power")
    values = tally.get_values(scores=["kappa-fission"]).ravel()
    fractions = values / values.sum()

    # Pin-level power in the centre assembly, normalised to the assembly mean.
    pins = params["assembly"]["lattice_size"]
    pin_tally = statepoint.get_tally(name="pin power")
    pin_values = pin_tally.get_values(scores=["kappa-fission"]).ravel()
    pin_grid = pin_values.reshape(pins, pins)
    filled = pin_grid[pin_grid > 0]
    pin_relative = pin_grid / filled.mean() if filled.size else pin_grid

    # Axial power and flux profiles (40 bins over the active height).
    z_edges = np.linspace(0.0, params["pin"]["active_fuel_length"], 41)
    z_centres = 0.5 * (z_edges[:-1] + z_edges[1:])
    axial_tally = statepoint.get_tally(name="axial profile")
    axial_values = axial_tally.get_values(
        scores=["kappa-fission", "flux"]
    ).reshape(-1, 2)
    axial_power = axial_values[:, 0] / axial_values[:, 0].mean()
    axial_flux = axial_values[:, 1] / axial_values[:, 1].mean()

    # Fuel and pin-cell water spectra.
    energy_edges = np.logspace(-5.0, 7.3, 61)
    energy_centres = np.sqrt(energy_edges[:-1] * energy_edges[1:])
    fuel_flux = statepoint.get_tally(name="fuel spectrum").get_values(
        scores=["flux"]
    ).ravel()
    water_flux = statepoint.get_tally(name="water spectrum").get_values(
        scores=["flux"]
    ).ravel()

    def spectrum_summary(flux):
        total = flux.sum()
        thermal = flux[energy_centres < 0.625].sum() / total
        fast = flux[energy_centres > 1.0e5].sum() / total
        mean_energy = float((flux * energy_centres).sum() / total)
        return {
            "thermal_fraction": float(thermal),
            "fast_fraction": float(fast),
            "mean_energy_eV": mean_energy,
        }

    nuclide_tally = statepoint.get_tally(name="nuclide rates")
    nuclide_values = nuclide_tally.get_values().reshape(
        len(nuclide_tally.nuclides), -1
    )
    u235_fission = float(nuclide_values[0, 0])
    u238_fission = float(nuclide_values[1, 0])
    fission_total = u235_fission + u238_fission

    size = params["core"]["layout_size"]
    pitch = params["core"]["lattice_pitch"]
    enrichment = {}
    for level, positions in params["core"]["enrichment_wt_pct"].items():
        for position in positions:
            enrichment[tuple(position)] = float(level)

    assemblies = []
    ring_power = {index: 0.0 for index in range(1, len(RINGS_CM) + 1)}
    for bin_index, fraction in enumerate(fractions):
        column = bin_index % size
        row = bin_index // size
        if fraction <= 0:
            continue
        radius = float(
            np.hypot(
                (column - (size - 1) / 2) * pitch,
                (row - (size - 1) / 2) * pitch,
            )
        )
        ring = ring_of(radius)
        ring_power[ring] += float(fraction)
        assemblies.append(
            {
                "column": column,
                "row": row,
                "enrichment_wt_pct": enrichment.get((column, row)),
                "radius_cm": round(radius, 3),
                "ring": ring,
                "power_fraction": float(fraction),
            }
        )

    k = getattr(statepoint, "keff", statepoint.k_combined)
    report = {
        "k_eff": float(k.nominal_value),
        "k_sigma": float(k.std_dev),
        "particles": args.particles,
        "batches": args.batches,
        "inactive": args.inactive,
        "thermal_power_mw": params["module"]["thermal_power_mw"],
        "assembly_count": len(assemblies),
        "assemblies": sorted(assemblies, key=lambda item: -item["power_fraction"]),
        "rings": [
            {
                "ring": index,
                "radius_cm": RINGS_CM[index - 1],
                "power_fraction": float(ring_power[index]),
                "power_w": float(ring_power[index] * params["module"]["thermal_power_mw"] * 1e6),
            }
            for index in sorted(ring_power)
        ],
        "densities_g_cm3": {
            f"{key[0]},{key[1]}": value
            for key, value in densities.items()
            if isinstance(key, tuple)
        },
        "downcomer_density_g_cm3": densities.get("downcomer"),
        "k_batches": [float(value) for value in statepoint.k_generation],
        "pin_power": {
            "assembly": [4, 4],
            "lattice_size": pins,
            "relative": pin_relative.tolist(),
        },
        "axial_power": {
            "z_cm": z_centres.tolist(),
            "relative": axial_power.tolist(),
            "flux_relative": axial_flux.tolist(),
        },
        "spectrum": {
            "energy_edges_eV": energy_edges.tolist(),
            "fuel_flux": fuel_flux.tolist(),
            "water_flux": water_flux.tolist(),
            "fuel": spectrum_summary(fuel_flux),
            "water": spectrum_summary(water_flux),
        },
        "nuclides": {
            "U235_fission": u235_fission,
            "U238_fission": u238_fission,
            "U235_absorption": float(nuclide_values[0, 1]),
            "U238_absorption": float(nuclide_values[1, 1]),
            "U235_fission_share": u235_fission / fission_total,
        },
    }

    output = os.path.join(args.out, "power.json")
    with open(output, "w") as handle:
        json.dump(report, handle, indent=2)
    print(
        f"k_eff = {report['k_eff']:.5f} +/- {report['k_sigma']:.5f}, "
        f"{len(assemblies)} assemblies, wrote {output}"
    )
    for ring in report["rings"]:
        print(f"  ring {ring['ring']}: {100 * ring['power_fraction']:.2f}% power")
    return 0


if __name__ == "__main__":
    sys.exit(main())
