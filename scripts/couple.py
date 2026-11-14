"""Iterate the OpenMC core and the OpenFOAM natural-circulation loop.

One iteration is

    OpenMC (per-assembly power)
        -> OpenFOAM (2D axisymmetric loop, radial ring heat source)
        -> ring temperatures -> water densities
        -> next OpenMC (per-assembly coolant density)

The loop stops after ``--iterations`` passes or when both k_eff and the ring
densities have stopped moving.  Everything is written below ``results/coupling``.
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUPLING = os.path.join(HERE, "results", "coupling")
WSL = "wsl.exe"
WSL_PYTHON = "/home/xander/openmc-env/bin/python"
WSL_CASE = "/home/xander/nsc_case"


def wsl_path(path):
    path = os.path.abspath(path)
    drive, rest = os.path.splitdrive(path)
    return "/mnt/" + drive[0].lower() + rest.replace("\\", "/")


def run(command):
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def openmc_power(out_dir, densities, particles, batches, inactive):
    command = [
        WSL,
        "bash",
        wsl_path(os.path.join(HERE, "scripts", "run_core_wsl.sh")),
        "--out",
        wsl_path(out_dir),
        "--particles",
        str(particles),
        "--batches",
        str(batches),
        "--inactive",
        str(inactive),
    ]
    if densities:
        command += ["--densities", wsl_path(densities)]
    run(command)


def foam_solve(power_json, end_time, max_delta_t, restart):
    run(
        [
            sys.executable,
            os.path.join(HERE, "scripts", "build_foam_case.py"),
            "--power",
            power_json,
            "--case",
            os.path.join(HERE, "results", "foam", "case"),
            "--end-time",
            str(end_time),
            "--max-delta-t",
            str(max_delta_t),
            "--write-interval",
            str(end_time / 5.0),
        ]
    )
    command = [
        WSL,
        "bash",
        wsl_path(os.path.join(HERE, "scripts", "run_foam_wsl.sh")),
        "results/foam/case",
    ]
    if restart:
        command.append("restart")
    run(command)


def foam_report(out_json, power_json):
    run(
        [
            WSL,
            "-e",
            WSL_PYTHON,
            wsl_path(os.path.join(HERE, "scripts", "foam_post.py")),
            "--case",
            WSL_CASE,
            "--power",
            wsl_path(power_json),
            "--out",
            wsl_path(out_json),
        ]
    )
    with open(out_json) as handle:
        return json.load(handle)


def densities_from_foam(power, foam):
    ring_density = {
        int(index): data["density_g_cm3"] for index, data in foam["rings"].items()
    }
    ring_temperature = {
        int(index): data["temperature_K"] for index, data in foam["rings"].items()
    }
    assemblies = {
        f"{item['column']},{item['row']}": ring_density[item["ring"]]
        for item in power["assemblies"]
    }
    return {
        "assemblies": assemblies,
        "downcomer": foam["downcomer_density_g_cm3"],
        "ring_temperature_K": ring_temperature,
        "ring_density_g_cm3": ring_density,
    }


def ring_change(previous, current):
    if not previous:
        return None
    common = set(previous) & set(current)
    if not common:
        return None
    return max(abs(previous[key] - current[key]) for key in common)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument(
        "--start-iteration",
        type=int,
        default=0,
        help="resume after a manually seeded earlier iteration",
    )
    parser.add_argument("--particles", type=int, default=5000)
    parser.add_argument("--batches", type=int, default=60)
    parser.add_argument("--inactive", type=int, default=20)
    parser.add_argument("--end-time", type=float, default=150.0)
    parser.add_argument(
        "--restart-end-time",
        type=float,
        default=60.0,
        help="shorter transient for iterations restarted from the previous field",
    )
    parser.add_argument("--max-delta-t", type=float, default=0.5)
    parser.add_argument("--density-tolerance", type=float, default=5.0e-3)
    parser.add_argument("--k-tolerance", type=float, default=5.0e-3)
    args = parser.parse_args(argv)

    os.makedirs(COUPLING, exist_ok=True)
    summary = {"iterations": [], "converged": False}
    previous_densities = None
    previous_k = None

    if args.start_iteration > 0:
        seed = os.path.join(COUPLING, f"iter{args.start_iteration - 1}")
        with open(os.path.join(seed, "densities.json")) as handle:
            previous_densities = {
                int(key): value
                for key, value in json.load(handle)["ring_density_g_cm3"].items()
            }
        with open(os.path.join(seed, "power.json")) as handle:
            previous_k = json.load(handle)["k_eff"]

    for index in range(args.start_iteration, args.iterations):
        out_dir = os.path.join(COUPLING, f"iter{index}")
        os.makedirs(out_dir, exist_ok=True)
        densities = (
            os.path.join(COUPLING, f"iter{index - 1}", "densities.json")
            if index
            else None
        )

        openmc_power(out_dir, densities, args.particles, args.batches, args.inactive)
        power_path = os.path.join(out_dir, "power.json")
        with open(power_path) as handle:
            power = json.load(handle)

        foam_solve(
            power_path,
            args.end_time if index == 0 else args.restart_end_time,
            args.max_delta_t,
            restart=index > 0,
        )
        foam = foam_report(os.path.join(out_dir, "foam.json"), power_path)

        feedback = densities_from_foam(power, foam)
        with open(os.path.join(out_dir, "densities.json"), "w") as handle:
            json.dump(feedback, handle, indent=2)

        change = ring_change(previous_densities, feedback["ring_density_g_cm3"])
        k_change = None if previous_k is None else abs(power["k_eff"] - previous_k)
        record = {
            "iteration": index,
            "k_eff": power["k_eff"],
            "k_sigma": power["k_sigma"],
            "k_change": k_change,
            "ring_temperature_K": feedback["ring_temperature_K"],
            "ring_density_g_cm3": feedback["ring_density_g_cm3"],
            "downcomer_temperature_K": foam["downcomer_temperature_K"],
            "downcomer_density_g_cm3": foam["downcomer_density_g_cm3"],
            "max_ring_density_change": change,
            "temperature_min_K": foam["temperature_min_K"],
            "temperature_max_K": foam["temperature_max_K"],
            "core_mean_velocity_z_m_s": foam["core_mean_velocity_z_m_s"],
            "downcomer_mean_velocity_z_m_s": foam["downcomer_mean_velocity_z_m_s"],
            "sg_inlet_temperature_K": foam.get("sg_inlet_temperature_K"),
            "sg_outlet_temperature_K": foam.get("sg_outlet_temperature_K"),
            "sg_duty_W": foam.get("sg_duty_W"),
            "core_power_W": foam.get("core_power_W"),
            "energy_imbalance": foam.get("energy_imbalance"),
        }
        summary["iterations"].append(record)
        with open(os.path.join(COUPLING, "summary.json"), "w") as handle:
            json.dump(summary, handle, indent=2)

        print(
            f"iteration {index}: k_eff = {power['k_eff']:.5f} +/- {power['k_sigma']:.5f}, "
            f"ring density change = {change if change is not None else 'n/a'}"
        )

        if (
            change is not None
            and k_change is not None
            and change < args.density_tolerance
            and k_change < args.k_tolerance
        ):
            summary["converged"] = True
            with open(os.path.join(COUPLING, "summary.json"), "w") as handle:
                json.dump(summary, handle, indent=2)
            print("coupled solution converged")
            break

        previous_densities = feedback["ring_density_g_cm3"]
        previous_k = power["k_eff"]

    print(f"wrote {os.path.join(COUPLING, 'summary.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
