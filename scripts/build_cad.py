"""Build the NuScale-like SMR CAD models and export STEP, STL and a 3D view.

Every level of detail is written to ``results/cad`` together with a manifest
that records volumes, bounding boxes and a few analytic cross checks.  The
manifest is the hand-off contract to the CAE side: an OpenMC or OpenFOAM case
can be generated from the same ``params/nuscale_core.json`` without looking at
the CAD files at all.
"""

import argparse
import json
import math
import os
import re
import sys

import cadquery as cq
import numpy as np
import plotly.graph_objects as go
from cadquery.occ_impl.exporters.assembly import exportAssembly

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nsc_bench import cad  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(HERE, "results", "cad")

LABELS = {
    "fuel_rod": "fuel rod (clad)",
    "guide_tube": "guide tube",
    "instrument_tube": "instrument tube",
    "pellet": "fuel pellet",
    "spacer_grid": "spacer grid",
    "bottom_nozzle": "bottom nozzle",
    "top_nozzle": "top nozzle",
    "heavy_reflector": "heavy reflector",
    "core_barrel": "core barrel",
    "downcomer": "downcomer water",
    "rpv": "pressure vessel",
    "rpv_shell": "pressure vessel",
    "cnv_shell": "containment vessel",
    "clad": "cladding",
    "fuel_pellet": "fuel pellet",
}


def _label(name):
    stem = re.sub(r"_\d+_\d+$", "", name)
    if stem.startswith("assembly_"):
        return "assembly"
    return LABELS.get(stem, stem.replace("_", " "))


def _rgba(color, default=(0.6, 0.6, 0.6, 1.0)):
    if color is None:
        return default
    rgba = color.toTuple()
    return tuple(rgba) if len(rgba) == 4 else tuple(rgba) + (1.0,)


def collect(assembly, tolerance):
    """Tessellate an assembly and merge the meshes per (label, colour)."""
    groups = {}
    parts = 0
    for item in assembly:
        obj, path, location, color = item
        if obj is None:
            continue
        shape = obj.val() if hasattr(obj, "val") else obj
        if not hasattr(shape, "tessellate"):
            continue
        shape = shape.located(location)
        vertices, triangles = shape.tessellate(tolerance)
        name = path.split("/")[-1]
        key = (_label(name), _rgba(color))
        group = groups.setdefault(
            key, {"vertices": [], "triangles": [], "offset": 0, "count": 0}
        )
        coordinates = np.array([[v.x, v.y, v.z] for v in vertices])
        indices = np.array(triangles, dtype=np.int64) + group["offset"]
        group["vertices"].append(coordinates)
        group["triangles"].append(indices)
        group["offset"] += len(coordinates)
        group["count"] += 1
        parts += 1

    merged = {}
    for (label, rgba), group in groups.items():
        merged[label, rgba] = {
            "vertices": np.concatenate(group["vertices"]),
            "triangles": np.concatenate(group["triangles"]),
            "rgba": rgba,
            "count": group["count"],
        }
    return merged, parts


def figure(meshes, title):
    traces = []
    for index, ((label, rgba), mesh) in enumerate(sorted(meshes.items())):
        red, green, blue = [int(255 * channel) for channel in rgba[:3]]
        traces.append(
            go.Mesh3d(
                x=mesh["vertices"][:, 0],
                y=mesh["vertices"][:, 1],
                z=mesh["vertices"][:, 2],
                i=mesh["triangles"][:, 0],
                j=mesh["triangles"][:, 1],
                k=mesh["triangles"][:, 2],
                name=label,
                color=f"rgb({red},{green},{blue})",
                opacity=rgba[3],
                showlegend=True,
                flatshading=True,
                lighting=dict(
                    ambient=0.55, diffuse=0.85, specular=0.15, roughness=0.9
                ),
                lightposition=dict(x=2000, y=-2500, z=3500),
                visible=True,
            )
        )
    layout = go.Layout(
        title=title,
        scene=dict(
            aspectmode="data",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            camera=dict(eye=dict(x=1.15, y=-1.05, z=0.55)),
            bgcolor="white",
        ),
        paper_bgcolor="white",
        margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(itemsizing="constant", font=dict(size=11)),
    )
    return go.Figure(data=traces, layout=layout)


def checks(params, level, assembly, bbox):
    """Analytic cross checks for the level that was just built."""
    pin = params["pin"]
    assembly_params = params["assembly"]
    core_params = params["core"]
    module = params["module"]
    results = []

    def add(name, expected, actual, unit="", less_than=False, tolerance=0.0):
        difference = abs(actual - expected)
        error = difference / expected if expected else 0.0
        if less_than:
            ok = actual <= expected
        else:
            ok = difference <= max(tolerance, 1e-6 * abs(expected))
        results.append(
            {
                "check": name,
                "expected": round(expected, 6),
                "actual": round(actual, 6),
                "unit": unit,
                "relative_error": error,
                "ok": bool(ok),
            }
        )

    if level == "pin":
        clad = assembly.objects["clad"].obj
        pellet = assembly.objects["fuel_pellet"].obj
        add(
            "clad volume (BRep vs pi(ro^2-ri^2)L)",
            math.pi
            * (pin["clad_outer_radius"] ** 2 - pin["clad_inner_radius"] ** 2)
            * pin["fuel_rod_length"],
            clad.Volume(),
            "cm3",
        )
        add(
            "pellet volume (BRep vs pi r^2 L)",
            math.pi * pin["pellet_radius"] ** 2 * pin["active_fuel_length"],
            pellet.Volume(),
            "cm3",
        )
        add("fuel rod length", pin["fuel_rod_length"], bbox.zmax - bbox.zmin, "cm", tolerance=1e-3)

    if level == "assembly":
        names = list(assembly.objects)
        add(
            "fuel rod count",
            17 * 17 - len(assembly_params["nonfuel_positions"]),
            sum(1 for name in names if name.startswith("fuel_rod")),
        )
        add(
            "guide tube count",
            len(assembly_params["nonfuel_positions"]) - 1,
            sum(1 for name in names if name.startswith("guide_tube")),
        )
        add(
            "assembly height",
            assembly_params["assembly_length"],
            bbox.zmax - bbox.zmin,
            "cm",
            tolerance=1e-3,
        )
        add(
            "assembly width",
            assembly_params["grid_strap_side"],
            bbox.xmax - bbox.xmin,
            "cm",
            tolerance=1e-3,
        )

    if level == "core":
        names = list(assembly.objects)
        add(
            "core assembly count",
            len(core_params["assembly_positions"]),
            sum(1 for name in names if name.startswith("assembly_")),
        )
        pitch = core_params["lattice_pitch"]
        half = (core_params["layout_size"] - 1) / 2.0
        corner = max(
            math.hypot(
                abs((column - half) * pitch) + pitch / 2,
                abs((row - half) * pitch) + pitch / 2,
            )
            for column, row in core_params["assembly_positions"]
        )
        add(
            "corner assembly radius < reflector inner radius",
            core_params["reflector_inner_radius"],
            corner,
            "cm",
            less_than=True,
        )

    if level == "module":
        add(
            "containment vessel height",
            module["cnv_height"],
            bbox.zmax - bbox.zmin,
            "cm",
            tolerance=1e-3,
        )
        rpv_box = assembly.objects["rpv_shell"].obj.BoundingBox()
        add(
            "pressure vessel outer diameter",
            2 * module["rpv_outer_radius"],
            rpv_box.xmax - rpv_box.xmin,
            "cm",
            tolerance=1e-3,
        )

    return results


def export(level, assembly, params, out_dir, tolerance, html):
    stem = os.path.join(out_dir, f"nuscale_{level}")
    step_path = stem + ".step"
    stl_path = stem + ".stl"
    html_path = stem + ".html"

    # Tessellation widens OCCT bounding boxes slightly, so measure first.
    bbox = assembly.toCompound().BoundingBox()
    level_checks = checks(params, level, assembly, bbox)

    exportAssembly(assembly, step_path, unit="CM")
    cq.exporters.export(
        assembly.toCompound(), stl_path, tolerance=tolerance, angularTolerance=0.3
    )

    meshes, part_count = collect(assembly, tolerance)
    if html:
        figure(meshes, f"NuScale-like SMR - {level}").write_html(
            html_path, include_plotlyjs=True, full_html=True
        )

    info = {
        "parts": part_count,
        "volume_litres": round(assembly.toCompound().Volume() * 1e-3, 3),
        "bounding_box_cm": {
            "x": [round(bbox.xmin, 3), round(bbox.xmax, 3)],
            "y": [round(bbox.ymin, 3), round(bbox.ymax, 3)],
            "z": [round(bbox.zmin, 3), round(bbox.zmax, 3)],
        },
        "step": os.path.relpath(step_path, HERE).replace("\\", "/"),
        "stl": os.path.relpath(stl_path, HERE).replace("\\", "/"),
        "html": os.path.relpath(html_path, HERE).replace("\\", "/") if html else None,
        "checks": level_checks,
    }
    return info


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--levels",
        default="pin,assembly,core,module",
        help="comma separated subset of pin,assembly,core,module",
    )
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--tolerance", type=float, default=0.15, help="tessellation, cm")
    parser.add_argument("--no-html", action="store_true")
    args = parser.parse_args(argv)

    params = cad.load_params()
    levels = [level.strip() for level in args.levels.split(",") if level.strip()]
    os.makedirs(args.out, exist_ok=True)

    report = {
        "params": os.path.relpath(cad.PARAMS_FILE, HERE).replace("\\", "/"),
        "units": "cm",
        "tessellation_cm": args.tolerance,
        "levels": {},
    }

    for level in levels:
        print(f"building {level} ...", flush=True)
        assembly = cad.build(level, params)
        info = export(level, assembly, params, args.out, args.tolerance, not args.no_html)
        report["levels"][level] = info
        print(
            f"  {info['parts']} solids, {info['volume_litres']} L, "
            f"bbox z {info['bounding_box_cm']['z']}",
            flush=True,
        )
        for check in info["checks"]:
            status = "ok" if check["ok"] else "FAIL"
            print(
                f"    [{status}] {check['check']}: "
                f"{check['actual']} vs {check['expected']} {check['unit']}",
                flush=True,
            )

    manifest = os.path.join(args.out, "manifest.json")
    with open(manifest, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"wrote {os.path.relpath(manifest, HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
