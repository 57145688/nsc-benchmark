"""CadQuery solid models of the NuScale-like SMR.

The geometry is driven by ``params/nuscale_core.json``, which transcribes the
dimensions used by the OpenMC model in ``mit-crpg/ecp-benchmarks`` (the same
model that the pin-cell benchmark in ``nsc_bench/model.py`` belongs to).

Four levels of detail are provided so that every CAE solver gets the geometry
it can actually consume:

``pin``        fuel pellet + cladding, for pin-cell comparisons
``assembly``   17x17 rod bundle, guide tubes, spacer grids, nozzles
``core``       37 assemblies, heavy reflector, core barrel, downcomer, RPV
``module``     RPV inside the steel containment vessel (CNV)

All lengths are centimetres, matching OpenMC.  The functions only build
geometry; export and rendering live in ``scripts/build_cad.py``.
"""

import json
import math
import os

import cadquery as cq

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS_FILE = os.path.join(HERE, "params", "nuscale_core.json")

# RGBA colours used by the renderer and by STEP export when available.
COLORS = {
    "fuel_3.1": (0.91, 0.45, 0.13, 1.0),
    "fuel_2.4": (0.95, 0.65, 0.20, 1.0),
    "fuel_1.6": (0.98, 0.83, 0.38, 1.0),
    "clad": (0.72, 0.74, 0.77, 1.0),
    "guide_tube": (0.52, 0.62, 0.70, 1.0),
    "nozzle": (0.48, 0.50, 0.53, 1.0),
    "grid": (0.62, 0.64, 0.66, 1.0),
    "barrel": (0.34, 0.42, 0.50, 1.0),
    "reflector": (0.24, 0.26, 0.30, 1.0),
    "water": (0.25, 0.55, 0.85, 0.30),
    "rpv": (0.55, 0.57, 0.60, 1.0),
    "cnv": (0.38, 0.60, 0.74, 0.18),
    "pellet": (0.80, 0.20, 0.08, 1.0),
}


def load_params(path=PARAMS_FILE):
    with open(path) as handle:
        return json.load(handle)


# ----------------------------------------------------------------- primitives


def cylinder(radius, height, z=0.0, x=0.0, y=0.0):
    return cq.Solid.makeCylinder(
        radius, height, cq.Vector(x, y, z), cq.Vector(0, 0, 1)
    )


def tube(inner_radius, outer_radius, height, z=0.0, x=0.0, y=0.0):
    return cylinder(outer_radius, height, z, x, y).cut(
        cylinder(inner_radius, height, z, x, y)
    )


def box(width_x, width_y, height, z=0.0, x=0.0, y=0.0):
    """Axis aligned box centred on (x, y) with its bottom face at z."""
    return cq.Solid.makeBox(
        width_x,
        width_y,
        height,
        cq.Vector(x - width_x / 2, y - width_y / 2, z),
        cq.Vector(0, 0, 1),
    )


def _profile_solid(points, segments=64):
    """Revolve a closed (r, z) profile around the Z axis.

    Elliptical heads are sampled so that the result is a regular BRep solid
    with explicit seam edges, which is what DAGMC meshers expect.
    """
    workplane = cq.Workplane("XZ").moveTo(*points[0])
    for point in points[1:]:
        workplane = workplane.lineTo(*point)
    wire = workplane.close().wire().val()
    face = cq.Face.makeFromWires(wire)
    return cq.Solid.revolve(
        face, 360, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1)
    )


def _ellipse(radius_r, radius_z, z_center, start_angle, end_angle, segments):
    points = []
    for index in range(segments + 1):
        angle = start_angle + (end_angle - start_angle) * index / segments
        points.append(
            (radius_r * math.sin(angle), z_center + radius_z * math.cos(angle))
        )
    return points


def thin_shell(outer_radius, wall, height, head_depth, z0=0.0, segments=64):
    """A cylinder closed by two 2:1 elliptical heads with a constant wall."""
    if wall >= min(outer_radius, head_depth):
        raise ValueError("wall is thicker than the head or the radius")
    straight_top = z0 + height - head_depth
    straight_bottom = z0 + head_depth
    inner_radius = outer_radius - wall
    inner_head_depth = head_depth - wall

    outer = [(0.0, z0)]
    outer += _ellipse(
        outer_radius, head_depth, straight_bottom, math.pi, math.pi / 2, segments
    )[1:]
    outer.append((outer_radius, straight_top))
    outer += _ellipse(
        outer_radius, head_depth, straight_top, math.pi / 2, 0.0, segments
    )[1:]

    inner = [(0.0, z0 + wall)]
    inner += _ellipse(
        inner_radius, inner_head_depth, straight_bottom, math.pi, math.pi / 2, segments
    )[1:]
    inner.append((inner_radius, straight_top))
    inner += _ellipse(
        inner_radius, inner_head_depth, straight_top, math.pi / 2, 0.0, segments
    )[1:]

    return _profile_solid(outer, segments).cut(_profile_solid(inner, segments))


# --------------------------------------------------------------------- models


def build_pin(params):
    """Single fuel rod: pellet stack inside the cladding tube."""
    pin = params["pin"]
    axial = params["axial"]
    rod_bottom = axial["fuel_rod"][0]
    fuel_bottom, fuel_top = axial["active_fuel"]

    assembly = cq.Assembly(name="fuel_rod")
    assembly.add(
        tube(
            pin["clad_inner_radius"],
            pin["clad_outer_radius"],
            pin["fuel_rod_length"],
            z=rod_bottom,
        ),
        name="clad",
        color=cq.Color(*COLORS["clad"]),
    )
    assembly.add(
        cylinder(
            pin["pellet_radius"],
            fuel_top - fuel_bottom,
            z=fuel_bottom,
        ),
        name="fuel_pellet",
        color=cq.Color(*COLORS["pellet"]),
    )
    return assembly


def build_assembly(params, include_pellets=False):
    """17x17 fuel assembly with guide tubes, spacer grids and nozzles."""
    pin = params["pin"]
    assembly_params = params["assembly"]
    axial = params["axial"]
    size = assembly_params["lattice_size"]
    pitch = pin["pin_pitch"]
    half = (size - 1) / 2.0
    nonfuel = {tuple(position) for position in assembly_params["nonfuel_positions"]}
    instrument = tuple(assembly_params["instrument_tube_position"])
    rod_bottom, rod_top = axial["fuel_rod"]
    rod_length = rod_top - rod_bottom
    fuel_bottom, fuel_top = axial["active_fuel"]

    assembly = cq.Assembly(name="fuel_assembly")

    for column in range(size):
        for row in range(size):
            x = (column - half) * pitch
            y = (row - half) * pitch
            if (column, row) in nonfuel:
                if (column, row) == instrument:
                    inner = pin["instrument_tube_inner_radius"]
                    outer = pin["instrument_tube_outer_radius"]
                    color = COLORS["guide_tube"]
                    name = "instrument_tube"
                else:
                    inner = pin["guide_tube_inner_radius"]
                    outer = pin["guide_tube_outer_radius"]
                    color = COLORS["guide_tube"]
                    name = "guide_tube"
                shape = tube(inner, outer, rod_length, z=rod_bottom, x=x, y=y)
            else:
                shape = tube(
                    pin["clad_inner_radius"],
                    pin["clad_outer_radius"],
                    rod_length,
                    z=rod_bottom,
                    x=x,
                    y=y,
                )
                color = COLORS["clad"]
                name = "fuel_rod"
            assembly.add(
                shape,
                name=f"{name}_{column}_{row}",
                color=cq.Color(*color),
            )
            if include_pellets and (column, row) not in nonfuel:
                assembly.add(
                    cylinder(
                        pin["pellet_radius"],
                        fuel_top - fuel_bottom,
                        z=fuel_bottom,
                        x=x,
                        y=y,
                    ),
                    name=f"pellet_{column}_{row}",
                    color=cq.Color(*COLORS["pellet"]),
                )

    outer = assembly_params["grid_strap_side"]
    inner = outer - 0.3
    for index, grid_z in enumerate(axial["grid_bottom_z"], start=1):
        frame = box(outer, outer, assembly_params["spacer_height"], z=grid_z).cut(
            box(
                inner,
                inner,
                assembly_params["spacer_height"] + 1.0,
                z=grid_z - 0.5,
            )
        )
        assembly.add(
            frame, name=f"spacer_grid_{index}", color=cq.Color(*COLORS["grid"])
        )

    nozzle_width = assembly_params["top_nozzle_width"]
    bottom_bottom, bottom_top = axial["bottom_nozzle"]
    top_bottom, top_top = axial["top_nozzle"]
    assembly.add(
        box(nozzle_width, nozzle_width, bottom_top - bottom_bottom, z=bottom_bottom),
        name="bottom_nozzle",
        color=cq.Color(*COLORS["nozzle"]),
    )
    assembly.add(
        box(nozzle_width, nozzle_width, top_top - top_bottom, z=top_bottom),
        name="top_nozzle",
        color=cq.Color(*COLORS["nozzle"]),
    )
    return assembly


def _enrichment_lookup(params):
    lookup = {}
    for enrichment, positions in params["core"]["enrichment_wt_pct"].items():
        for position in positions:
            lookup[tuple(position)] = enrichment
    return lookup


def build_core(params, include_rpv=True):
    """37-assembly core, heavy reflector, core barrel, downcomer and RPV."""
    core_params = params["core"]
    assembly_length = params["assembly"]["assembly_length"]
    pitch = core_params["lattice_pitch"]
    half = (core_params["layout_size"] - 1) / 2.0
    enrichment = _enrichment_lookup(params)

    assembly = cq.Assembly(name="core")
    for column, row in core_params["assembly_positions"]:
        key = enrichment.get((column, row), "1.6")
        assembly.add(
            box(
                pitch,
                pitch,
                assembly_length,
                x=(column - half) * pitch,
                y=(row - half) * pitch,
            ),
            name=f"assembly_{column}_{row}",
            color=cq.Color(*COLORS[f"fuel_{key}"]),
        )

    barrel_z = core_params["core_barrel_bottom_z"]
    barrel_height = core_params["core_barrel_height"]

    assembly.add(
        tube(
            core_params["reflector_inner_radius"],
            core_params["core_barrel_inner_radius"],
            assembly_length,
        ),
        name="heavy_reflector",
        color=cq.Color(*COLORS["reflector"]),
    )
    assembly.add(
        tube(
            core_params["core_barrel_inner_radius"],
            core_params["core_barrel_outer_radius"],
            barrel_height,
            z=barrel_z,
        ),
        name="core_barrel",
        color=cq.Color(*COLORS["barrel"]),
    )
    assembly.add(
        tube(
            core_params["core_barrel_outer_radius"],
            core_params["rpv_inner_radius"],
            barrel_height,
            z=barrel_z,
        ),
        name="downcomer",
        color=cq.Color(*COLORS["water"]),
    )
    if include_rpv:
        assembly.add(
            tube(
                core_params["rpv_inner_radius"],
                core_params["rpv_outer_radius"],
                barrel_height,
                z=barrel_z,
            ),
            name="rpv",
            color=cq.Color(*COLORS["rpv"]),
        )
    return assembly


def build_module(params):
    """RPV inside the steel containment vessel, with the core placed in the RPV."""
    module = params["module"]
    core_params = params["core"]

    assembly = cq.Assembly(name="module")
    assembly.add(
        thin_shell(
            module["rpv_outer_radius"],
            module["rpv_shell_thickness"],
            module["rpv_height"],
            module["rpv_head_depth"],
            z0=module["rpv_bottom_z"],
        ),
        name="rpv_shell",
        color=cq.Color(*COLORS["rpv"]),
    )
    assembly.add(
        thin_shell(
            module["cnv_outer_radius"],
            module["cnv_shell_thickness"],
            module["cnv_height"],
            module["cnv_head_depth"],
            z0=0.0,
        ),
        name="cnv_shell",
        color=cq.Color(*COLORS["cnv"]),
    )

    core = build_core(params, include_rpv=False)
    # lift the core stack so that it sits in the lower half of the vessel
    core_bottom = module["rpv_bottom_z"] + 250.0
    assembly.add(
        core,
        name="core",
        loc=cq.Location(cq.Vector(0, 0, core_bottom)),
    )
    return assembly


BUILDERS = {
    "pin": build_pin,
    "assembly": build_assembly,
    "core": build_core,
    "module": build_module,
}


def build(level, params=None):
    params = params or load_params()
    return BUILDERS[level](params)
