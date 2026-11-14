"""Build the CFD figures and the animation used in the report gallery.

    python scripts/make_figures.py --power results/coupling/iter2/power.json

Writes temperature/velocity maps, the energy-balance history, a GIF of the
temperature field and a 3D cutaway of the CFD zones to ``results/figures``.
"""

import argparse
import glob
import json
import os
import sys
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import build_foam_case as case  # noqa: E402
from scripts import foam_post as post  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "results", "figures")
CASE = os.path.join(HERE, "results", "foam", "case")

R_EDGES = np.linspace(case.R0, case.R_RPV, post.NR + 1)
Z_EDGES = np.linspace(case.Z_BOTTOM, case.Z_TOP, post.NZ + 1)
R_CENTRES = 0.5 * (R_EDGES[:-1] + R_EDGES[1:])
Z_CENTRES = 0.5 * (Z_EDGES[:-1] + Z_EDGES[1:])

ZONES = [
    ("core", 0.05, case.CORE_RADIUS, case.CORE_Z, "#e4572e"),
    ("riser", 0.05, case.CORE_RADIUS, case.RISER_Z, "#8fb8de"),
    ("shroud", *case.SHROUD_RADII, (0.0, case.SG_Z[1]), "#9aa5b1"),
    ("sg", *case.SG_RADII, case.SG_Z, "#2a9d8f"),
    ("downcomer", *case.DOWNCOMER_RADII, (0.0, case.SG_Z[0]), "#4361ee"),
]


def time_dirs(case_dir):
    values = []
    for name in os.listdir(case_dir):
        try:
            number = float(name)
        except ValueError:
            continue
        if number > 0.0:
            values.append((number, name))
    return [name for _, name in sorted(values)]


def fields(case_dir, time):
    temperature = post.read_field(case_dir, time, "T").reshape(post.NZ, post.NR)
    velocity = post.read_field(case_dir, time, "U").reshape(post.NZ, post.NR, 3)
    return temperature, velocity


def draw_zones(ax, labels=True, text_size=8):
    for name, r0, r1, (z0, z1), color in ZONES:
        if name == "shroud":
            ax.plot([r0, r0], [z0, z1], color=color, lw=3, solid_capstyle="butt")
            ax.plot([r1, r1], [z0, z1], color=color, lw=1, ls="--")
        else:
            ax.add_patch(
                Rectangle(
                    (r0, z0),
                    r1 - r0,
                    z1 - z0,
                    fill=False,
                    edgecolor=color,
                    lw=1.4,
                    ls="--",
                )
            )
        if labels:
            ax.text(
                (r0 + r1) / 2.0,
                (z0 + z1) / 2.0,
                name,
                color="white",
                fontsize=text_size,
                ha="center",
                va="center",
                bbox=dict(facecolor="black", alpha=0.35, pad=1.5, lw=0),
            )


def finish_axes(ax):
    ax.set_xlabel("r / m")
    ax.set_ylabel("z / m")
    ax.set_xlim(case.R0, case.R_RPV)
    ax.set_ylim(case.Z_BOTTOM, case.Z_TOP)
    ax.set_aspect("equal")
    ax.set_facecolor("#101418")


def temperature_map(case_dir, time, path, label=None):
    temperature, _ = fields(case_dir, time)
    figure, ax = plt.subplots(figsize=(4.6, 9.6), constrained_layout=True)
    mesh = ax.pcolormesh(
        R_EDGES, Z_EDGES, temperature, shading="flat", cmap="inferno"
    )
    draw_zones(ax)
    finish_axes(ax)
    colour = figure.colorbar(mesh, ax=ax, pad=0.02)
    colour.set_label("temperature / K")
    title = "coolant temperature, 5 deg wedge"
    if label:
        title += f"  (t = {label})"
    ax.set_title(title)
    figure.savefig(path, dpi=140)
    plt.close(figure)


def velocity_map(case_dir, time, path):
    temperature, velocity = fields(case_dir, time)
    axial = velocity[:, :, 2]
    figure, ax = plt.subplots(figsize=(4.6, 9.6), constrained_layout=True)
    mesh = ax.pcolormesh(
        R_EDGES,
        Z_EDGES,
        axial,
        shading="flat",
        cmap="coolwarm",
        vmin=-0.5,
        vmax=0.5,
    )
    step = 10
    sub_r = R_CENTRES[::step]
    sub_z = Z_CENTRES[::step]
    radial = velocity[::step, ::step, 0]
    axial_sub = velocity[::step, ::step, 2]
    magnitude = np.hypot(radial, axial_sub)
    r_grid, z_grid = np.meshgrid(sub_r, sub_z)
    ax.quiver(
        r_grid,
        z_grid,
        radial / (magnitude + 1e-9),
        axial_sub / (magnitude + 1e-9),
        color="black",
        alpha=0.6,
        scale=2.0,
        scale_units="inches",
        width=0.0030,
        headwidth=3.5,
    )
    draw_zones(ax)
    finish_axes(ax)
    colour = figure.colorbar(mesh, ax=ax, pad=0.02)
    colour.set_label("axial velocity / m s$^{-1}$ (clipped at +/-0.5)")
    ax.set_title("vertical flow: red up, blue down")
    figure.savefig(path, dpi=140)
    plt.close(figure)


def energy_history(case_dir, power_json, path):
    times = time_dirs(case_dir)
    history = []
    with tempfile.TemporaryDirectory() as scratch:
        for index, time in enumerate(times):
            target = os.path.join(scratch, f"report_{index}.json")
            with open(os.devnull, "w") as sink:
                stdout, sys.stdout = sys.stdout, sink
                try:
                    post.main(
                        [
                            "--case",
                            case_dir,
                            "--time",
                            time,
                            "--power",
                            power_json,
                            "--out",
                            target,
                        ]
                    )
                finally:
                    sys.stdout = stdout
            with open(target) as handle:
                report = json.load(handle)
            history.append((float(time), report))

    seconds = [entry[0] for entry in history]
    duty = [entry[1]["sg_duty_W"] / 1e6 for entry in history]
    rated = history[0][1]["core_power_W"] / 1e6
    imbalance = [100.0 * entry[1]["energy_imbalance"] for entry in history]

    figure, (left, right) = plt.subplots(
        1, 2, figsize=(11, 4.2), constrained_layout=True
    )
    left.plot(seconds, duty, "o-", color="#2a9d8f", label="SG duty")
    left.axhline(rated, color="#e4572e", ls="--", label="core power (wedge)")
    left.set_xlabel("time / s")
    left.set_ylabel("power / MW")
    left.set_title("steam generator heat removal")
    left.grid(alpha=0.3)
    left.legend(frameon=False)

    right.semilogy(seconds, imbalance, "o-", color="#4361ee")
    right.set_xlabel("time / s")
    right.set_ylabel("|SG - core| / %")
    right.set_title("energy balance error")
    right.grid(alpha=0.3, which="both")
    figure.savefig(path, dpi=140)
    plt.close(figure)

    return history


def temperature_animation(case_dir, path, fps=2):
    times = time_dirs(case_dir)
    frames = []
    low = high = None
    for time in times:
        temperature, _ = fields(case_dir, time)
        low = temperature.min() if low is None else min(low, temperature.min())
        high = temperature.max() if high is None else max(high, temperature.max())

    with tempfile.TemporaryDirectory() as scratch:
        for index, time in enumerate(times):
            temperature, _ = fields(case_dir, time)
            figure, ax = plt.subplots(
                figsize=(4.6, 8.4), constrained_layout=True
            )
            mesh = ax.pcolormesh(
                R_EDGES,
                Z_EDGES,
                temperature,
                shading="flat",
                cmap="inferno",
                vmin=low,
                vmax=high,
            )
            draw_zones(ax)
            finish_axes(ax)
            colour = figure.colorbar(mesh, ax=ax, pad=0.02)
            colour.set_label("temperature / K")
            ax.set_title(f"coolant temperature, t = {float(time):.0f} s")
            frame = os.path.join(scratch, f"frame_{index:03d}.png")
            figure.savefig(frame, dpi=110)
            plt.close(figure)
            frames.append(Image.open(frame).convert("P", palette=Image.ADAPTIVE))

        duration = int(1000 / fps)
        frames[0].save(
            path,
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            optimize=True,
        )
    print(f"wrote {path} ({len(frames)} frames)")


def annulus(ax, r0, r1, z0, z1, color, alpha=0.35, theta=(np.pi / 2, 3 * np.pi / 2)):
    theta_values = np.linspace(theta[0], theta[1], 80)
    z_values = np.linspace(z0, z1, 2)
    theta_grid, z_grid = np.meshgrid(theta_values, z_values)
    for radius in (r0, r1):
        ax.plot_surface(
            radius * np.cos(theta_grid),
            radius * np.sin(theta_grid),
            z_grid,
            color=color,
            alpha=alpha,
            linewidth=0,
            shade=True,
        )
    for z_value in (z0, z1):
        radial = np.linspace(r0, r1, 2)
        theta_grid, radial_grid = np.meshgrid(theta_values, radial)
        ax.plot_surface(
            radial_grid * np.cos(theta_grid),
            radial_grid * np.sin(theta_grid),
            np.full_like(radial_grid, z_value),
            color=color,
            alpha=alpha,
            linewidth=0,
            shade=True,
        )


def model_3d(path):
    figure = plt.figure(figsize=(6.4, 9.0))
    ax = figure.add_subplot(projection="3d")
    ax.set_position([0.02, 0.05, 0.78, 0.86])
    colours = {
        "core": "#e4572e",
        "riser": "#8fb8de",
        "shroud": "#9aa5b1",
        "sg": "#2a9d8f",
        "downcomer": "#4361ee",
    }
    annulus(ax, 0.05, case.CORE_RADIUS, *case.CORE_Z, colours["core"], 0.65)
    annulus(ax, 0.05, case.CORE_RADIUS, *case.RISER_Z, colours["riser"], 0.25)
    annulus(ax, case.SG_RADII[0], case.SG_RADII[1], *case.SG_Z, colours["sg"], 0.40)
    annulus(
        ax,
        case.DOWNCOMER_RADII[0],
        case.DOWNCOMER_RADII[1],
        0.0,
        case.SG_Z[0],
        colours["downcomer"],
        0.28,
    )
    annulus(ax, *case.SHROUD_RADII, 0.0, case.SG_Z[1], colours["shroud"], 0.55)
    ax.set_zlabel("z / m")
    ax.set_box_aspect((1.4, 1.4, 6.0))
    ax.view_init(elev=16, azim=-28)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks(np.arange(0, 9, 2))
    ax.tick_params(axis="z", labelsize=8)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.set_facecolor((1.0, 1.0, 1.0, 0.0))
        axis.pane.set_edgecolor((1.0, 1.0, 1.0, 0.0))
    ax.set_title("CFD domain: half section of the loop", pad=0)
    handles = [
        Rectangle((0, 0), 1, 1, color=colours["core"], alpha=0.7),
        Rectangle((0, 0), 1, 1, color=colours["riser"], alpha=0.7),
        Rectangle((0, 0), 1, 1, color=colours["sg"], alpha=0.7),
        Rectangle((0, 0), 1, 1, color=colours["downcomer"], alpha=0.7),
        Rectangle((0, 0), 1, 1, color=colours["shroud"], alpha=0.7),
    ]
    ax.legend(
        handles,
        ["porous core", "hot riser", "SG (heat exchanger)", "downcomer", "barrel"],
        loc="upper left",
        bbox_to_anchor=(0.0, 1.0),
        frameon=False,
        fontsize=8,
    )
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--power", default=os.path.join(HERE, "results", "coupling", "iter2", "power.json")
    )
    parser.add_argument("--case", default=CASE)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    times = time_dirs(args.case)
    final = times[-1]

    temperature_map(args.case, final, os.path.join(args.out, "cfd_temperature.png"))
    velocity_map(args.case, final, os.path.join(args.out, "cfd_velocity.png"))
    energy_history(
        args.case, args.power, os.path.join(args.out, "cfd_energy_balance.png")
    )
    temperature_animation(args.case, os.path.join(args.out, "cfd_temperature.gif"))
    model_3d(os.path.join(args.out, "cfd_domain_3d.png"))
    print(f"figures written for t = {final} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
