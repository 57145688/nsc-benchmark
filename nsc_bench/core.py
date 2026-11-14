"""37-assembly NuScale-like core for the OpenMC side of the coupling loop.

The model is a 2D radial slice (reflective top and bottom) built from the same
``params/nuscale_core.json`` used by the CAD.  Every assembly carries its own
water material so that a coolant density field coming from OpenFOAM can be fed
back without rebuilding the geometry.

The pin-by-pin lattice follows the ecp-benchmarks layout: 264 fuel rods, 24
guide tubes and one instrument tube per assembly, with 1.6/2.4/3.1 wt%
enrichment zones in a 9x9 core lattice.
"""

import json
import os

import numpy as np
import openmc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS_FILE = os.path.join(HERE, "params", "nuscale_core.json")


def load_params(path=PARAMS_FILE):
    with open(path) as handle:
        return json.load(handle)


def _fuel(enrichment):
    material = openmc.Material(name=f"UO2 {enrichment}%")
    material.add_element("U", 1.0, enrichment=enrichment, enrichment_type="wo")
    material.add_element("O", 2.0)
    material.set_density("g/cm3", 10.4)
    material.temperature = 294.0
    return material


def _clad():
    material = openmc.Material(name="Zircaloy-4")
    material.set_density("g/cm3", 6.55)
    material.add_element("O", 0.00125, "wo")
    material.add_element("Cr", 0.0010, "wo")
    material.add_element("Fe", 0.0021, "wo")
    material.add_element("Zr", 0.98115, "wo")
    material.add_element("Sn", 0.0145, "wo")
    material.temperature = 294.0
    return material


def _water(name, density):
    material = openmc.Material(name=name)
    material.set_density("g/cm3", density)
    material.add_element("H", 2.0)
    material.add_element("O", 1.0)
    material.add_s_alpha_beta("c_H_in_H2O")
    material.temperature = 294.0
    return material


def _ss304():
    material = openmc.Material(name="SS304")
    material.set_density("g/cm3", 8.03)
    material.add_element("Si", 0.006, "wo")
    material.add_element("Cr", 0.19, "wo")
    material.add_element("Mn", 0.02, "wo")
    material.add_element("Fe", 0.684, "wo")
    material.add_element("Ni", 0.10, "wo")
    material.temperature = 294.0
    return material


def _helium():
    material = openmc.Material(name="Helium gap")
    material.set_density("g/cm3", 0.000178)
    material.add_element("He", 1.0)
    material.temperature = 294.0
    return material


def _square_region(width):
    """Square prism centred on the origin, built from four planes."""
    half = width / 2.0
    left = openmc.XPlane(x0=-half)
    right = openmc.XPlane(x0=half)
    bottom = openmc.YPlane(y0=-half)
    top = openmc.YPlane(y0=half)
    return +left & -right & +bottom & -top


class Surfaces:
    """One instance of every surface so cells share exactly the same objects."""

    def __init__(self, params):
        pin = params["pin"]
        core = params["core"]
        self.pellet = openmc.ZCylinder(r=pin["pellet_radius"])
        self.clad_inner = openmc.ZCylinder(r=pin["clad_inner_radius"])
        self.clad_outer = openmc.ZCylinder(r=pin["clad_outer_radius"])
        self.guide_inner = openmc.ZCylinder(r=pin["guide_tube_inner_radius"])
        self.guide_outer = openmc.ZCylinder(r=pin["guide_tube_outer_radius"])
        self.instrument_inner = openmc.ZCylinder(
            r=pin["instrument_tube_inner_radius"]
        )
        self.instrument_outer = openmc.ZCylinder(
            r=pin["instrument_tube_outer_radius"]
        )
        self.pin_box = _square_region(pin["pin_pitch"])
        self.lattice_box = _square_region(
            params["assembly"]["lattice_size"] * pin["pin_pitch"]
        )
        self.assembly_box = _square_region(params["assembly"]["lattice_pitch"])
        self.barrel_inner = openmc.ZCylinder(r=core["core_barrel_inner_radius"])
        self.barrel_outer = openmc.ZCylinder(r=core["core_barrel_outer_radius"])
        self.rpv_inner = openmc.ZCylinder(r=core["rpv_inner_radius"])
        self.rpv_outer = openmc.ZCylinder(
            r=core["rpv_outer_radius"], boundary_type="vacuum"
        )
        self.z_bottom = openmc.ZPlane(
            z0=0.0, boundary_type="reflective"
        )
        self.z_top = openmc.ZPlane(
            z0=pin["active_fuel_length"], boundary_type="reflective"
        )


def _fuel_pin_universe(fuel, water, clad, helium, surfaces):
    fuel_cell = openmc.Cell(name="fuel", fill=fuel, region=-surfaces.pellet)
    gap_cell = openmc.Cell(
        name="gap", fill=helium, region=+surfaces.pellet & -surfaces.clad_inner
    )
    clad_cell = openmc.Cell(
        name="clad", fill=clad, region=+surfaces.clad_inner & -surfaces.clad_outer
    )
    water_cell = openmc.Cell(
        name="pin water", fill=water, region=+surfaces.clad_outer & surfaces.pin_box
    )
    universe = openmc.Universe(
        cells=[fuel_cell, gap_cell, clad_cell, water_cell]
    )
    return universe, fuel_cell, water_cell


def _tube_universe(inner, outer, water, clad, surfaces):
    return openmc.Universe(
        cells=[
            openmc.Cell(fill=water, region=-inner),
            openmc.Cell(fill=clad, region=+inner & -outer),
            openmc.Cell(fill=water, region=+outer & surfaces.pin_box),
        ]
    )


def _assembly_universe(params, water, fuel_pin, guide, instrument, surfaces):
    assembly = params["assembly"]
    pin = params["pin"]
    size = assembly["lattice_size"]
    pitch = pin["pin_pitch"]
    nonfuel = {tuple(position) for position in assembly["nonfuel_positions"]}
    instrument_position = tuple(assembly["instrument_tube_position"])

    universes = np.full((size, size), fuel_pin, dtype=object)
    for column, row in nonfuel:
        universes[column, row] = (
            instrument if (column, row) == instrument_position else guide
        )

    lattice = openmc.RectLattice(name="assembly lattice")
    lattice.lower_left = (-size * pitch / 2.0, -size * pitch / 2.0)
    lattice.pitch = (pitch, pitch)
    lattice.universes = universes

    return openmc.Universe(
        cells=[
            openmc.Cell(fill=lattice, region=surfaces.lattice_box),
            openmc.Cell(
                fill=water,
                region=~surfaces.lattice_box & surfaces.assembly_box,
            ),
        ]
    )


def assembly_keys(params):
    return [tuple(position) for position in params["core"]["assembly_positions"]]


def default_densities(params):
    return {key: 0.998 for key in assembly_keys(params)}


def build_model(params=None, densities=None, particles=10000, batches=120, inactive=30):
    """Build the 2D core.

    ``densities`` maps an assembly lattice index ``(column, row)`` to a coolant
    density in g/cm3.  Missing keys fall back to the cold density.
    """
    params = params or load_params()
    core = params["core"]
    pin = params["pin"]
    assembly = params["assembly"]
    densities = densities or {}

    surfaces = Surfaces(params)
    clad = _clad()
    helium = _helium()
    ss = _ss304()

    key_to_enrichment = {}
    for enrichment, positions in core["enrichment_wt_pct"].items():
        for position in positions:
            key_to_enrichment[tuple(position)] = float(enrichment)
    fuel_materials = {
        enrichment: _fuel(enrichment)
        for enrichment in sorted(set(key_to_enrichment.values()))
    }

    assembly_universes = {}
    water_materials = {}
    centre_fuel = None
    centre_water = None
    for key in assembly_keys(params):
        water = _water(f"water {key[0]},{key[1]}", densities.get(key, 0.998))
        water_materials[key] = water
        fuel_pin, fuel_cell, water_cell = _fuel_pin_universe(
            fuel_materials[key_to_enrichment.get(key, 1.6)],
            water,
            clad,
            helium,
            surfaces,
        )
        if key == (4, 4):
            centre_fuel, centre_water = fuel_cell, water_cell
        guide = _tube_universe(
            surfaces.guide_inner,
            surfaces.guide_outer,
            water,
            clad,
            surfaces,
        )
        instrument = _tube_universe(
            surfaces.instrument_inner,
            surfaces.instrument_outer,
            water,
            clad,
            surfaces,
        )
        assembly_universes[key] = _assembly_universe(
            params, water, fuel_pin, guide, instrument, surfaces
        )

    reflector = openmc.Universe(
        cells=[openmc.Cell(fill=ss, region=surfaces.assembly_box)]
    )

    size = core["layout_size"]
    pitch = core["lattice_pitch"]
    universes = np.full((size, size), reflector, dtype=object)
    for key, universe in assembly_universes.items():
        universes[key[0], key[1]] = universe

    lattice = openmc.RectLattice(name="core lattice")
    lattice.lower_left = (-size * pitch / 2.0, -size * pitch / 2.0)
    lattice.pitch = (pitch, pitch)
    lattice.universes = universes

    core_cell = openmc.Cell(
        fill=lattice,
        region=-surfaces.barrel_inner & +surfaces.z_bottom & -surfaces.z_top,
    )
    barrel = openmc.Cell(
        fill=ss,
        region=+surfaces.barrel_inner
        & -surfaces.barrel_outer
        & +surfaces.z_bottom
        & -surfaces.z_top,
    )
    downcomer_water = _water(
        "downcomer water", densities.get("downcomer", 0.998)
    )
    downcomer = openmc.Cell(
        fill=downcomer_water,
        region=+surfaces.barrel_outer
        & -surfaces.rpv_inner
        & +surfaces.z_bottom
        & -surfaces.z_top,
    )
    rpv = openmc.Cell(
        fill=ss,
        region=+surfaces.rpv_inner
        & -surfaces.rpv_outer
        & +surfaces.z_bottom
        & -surfaces.z_top,
    )
    geometry = openmc.Geometry([core_cell, barrel, downcomer, rpv])

    materials = openmc.Materials(
        [clad, helium, ss, downcomer_water]
        + list(fuel_materials.values())
        + list(water_materials.values())
    )

    z0 = 0.0
    z1 = pin["active_fuel_length"]
    settings = openmc.Settings()
    settings.run_mode = "eigenvalue"
    settings.batches = batches
    settings.inactive = inactive
    settings.particles = particles
    settings.temperature = {"default": 294.0, "method": "nearest"}
    settings.source = openmc.IndependentSource(
        space=openmc.stats.Box(
            [-0.8 * size * pitch / 2, -0.8 * size * pitch / 2, z0],
            [0.8 * size * pitch / 2, 0.8 * size * pitch / 2, z1],
        )
    )

    mesh = openmc.RegularMesh(name="assembly mesh")
    mesh.dimension = [size, size, 1]
    mesh.lower_left = [-size * pitch / 2, -size * pitch / 2, z0]
    mesh.upper_right = [size * pitch / 2, size * pitch / 2, z1]

    power = openmc.Tally(name="assembly power")
    power.filters = [openmc.MeshFilter(mesh)]
    power.scores = ["kappa-fission", "fission", "absorption", "flux"]

    # Pin-level mesh over the centre assembly (4,4), which sits at the origin.
    pin_pitch = pin["pin_pitch"]
    pins = assembly["lattice_size"]
    pin_mesh = openmc.RegularMesh(name="pin mesh")
    pin_mesh.dimension = [pins, pins, 1]
    pin_mesh.lower_left = [-pins * pin_pitch / 2.0, -pins * pin_pitch / 2.0, z0]
    pin_mesh.upper_right = [pins * pin_pitch / 2.0, pins * pin_pitch / 2.0, z1]
    pin_power = openmc.Tally(name="pin power")
    pin_power.filters = [openmc.MeshFilter(pin_mesh)]
    pin_power.scores = ["kappa-fission"]

    # Axial power and flux profile over the whole barrel cross-section.
    axial_mesh = openmc.RegularMesh(name="axial mesh")
    axial_mesh.dimension = [1, 1, 40]
    axial_mesh.lower_left = [
        -core["core_barrel_inner_radius"],
        -core["core_barrel_inner_radius"],
        z0,
    ]
    axial_mesh.upper_right = [
        core["core_barrel_inner_radius"],
        core["core_barrel_inner_radius"],
        z1,
    ]
    axial = openmc.Tally(name="axial profile")
    axial.filters = [openmc.MeshFilter(axial_mesh)]
    axial.scores = ["kappa-fission", "flux"]

    # Spectrum in one fuel pin and in the surrounding pin-cell water.
    energy_bins = np.logspace(-5.0, 7.3, 61)
    energy = openmc.EnergyFilter(energy_bins)
    fuel_spectrum = openmc.Tally(name="fuel spectrum")
    fuel_spectrum.filters = [openmc.CellFilter([centre_fuel.id]), energy]
    fuel_spectrum.scores = ["flux"]
    water_spectrum = openmc.Tally(name="water spectrum")
    water_spectrum.filters = [openmc.CellFilter([centre_water.id]), energy]
    water_spectrum.scores = ["flux"]

    # Nuclide-wise fission and absorption in the whole core.
    nuclides = openmc.Tally(name="nuclide rates")
    nuclides.nuclides = ["U235", "U238"]
    nuclides.scores = ["fission", "absorption"]

    tallies = openmc.Tallies(
        [power, pin_power, axial, fuel_spectrum, water_spectrum, nuclides]
    )

    return (
        openmc.Model(
            geometry=geometry,
            materials=materials,
            settings=settings,
            tallies=tallies,
        ),
        mesh,
        water_materials,
    )
