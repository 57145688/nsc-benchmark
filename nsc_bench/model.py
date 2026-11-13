"""Single pin cell of the NuScale 17x17 fuel assembly.

The geometry is a square cell of side ``pitch`` with reflective boundaries, so
the multiplication factor it returns is k_inf.  Everything is parametric and
driven by ``params/uscale_pin.json``.

Units are cm and the temperature is in kelvin.
"""

import json
import os

import openmc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS_FILE = os.path.join(HERE, "params", "nuscale_pin.json")


def load_params(path=PARAMS_FILE):
    with open(path) as handle:
        return json.load(handle)


def boron_atom_fraction(boron_ppm, water_density):
    """Boron atom fraction relative to the atoms of the water molecule.

    ``Material.add_element`` expects relative atom fractions, not an absolute
    number density, so the ppm concentration is converted to a fraction of the
    three atoms in H2O.
    """
    avogadro = 6.02214076e23
    water_molar_mass = 18.015  # g/mol
    boron_molar_mass = 10.81  # g/mol, natural boron
    water_atoms = 3 * water_density / water_molar_mass * avogadro
    boron_atoms = water_density * boron_ppm * 1e-6 / boron_molar_mass * avogadro
    return boron_atoms / water_atoms


def make_materials(params, boron_ppm):
    fuel = openmc.Material(name="fuel")
    fuel.add_element(
        "U", 1.0, enrichment=params["u235_enrichment_wt_pct"], enrichment_type="wo"
    )
    fuel.add_element("O", 2.0)
    fuel.set_density("g/cm3", params["fuel_density_g_cm3"])

    clad = openmc.Material(name="clad")
    clad.add_element("Zr", 98.2, percent_type="wo")
    clad.add_element("Sn", 1.5, percent_type="wo")
    clad.add_element("Fe", 0.2, percent_type="wo")
    clad.add_element("Cr", 0.1, percent_type="wo")
    clad.set_density("g/cm3", params["clad_density_g_cm3"])

    water = openmc.Material(name="water")
    water.add_element("H", 2.0)
    water.add_element("O", 1.0)
    water.set_density("g/cm3", params["water_density_g_cm3"])
    water.add_s_alpha_beta("c_H_in_H2O")
    if boron_ppm > 0:
        water.add_element(
            "B", boron_atom_fraction(boron_ppm, params["water_density_g_cm3"])
        )

    for material in (fuel, clad, water):
        material.temperature = params["temperature_K"]

    return fuel, clad, water


def build_model(boron_ppm, params=None):
    params = params or load_params()
    fuel, clad, water = make_materials(params, boron_ppm)

    inner = openmc.ZCylinder(r=params["fuel_radius_cm"])
    outer = openmc.ZCylinder(r=params["clad_outer_radius_cm"])
    boundary = openmc.model.rectangular_prism(
        params["pitch_cm"], params["pitch_cm"], boundary_type="reflective"
    )

    fuel_cell = openmc.Cell(name="fuel", region=-inner, fill=fuel)
    clad_cell = openmc.Cell(name="clad", region=+inner & -outer, fill=clad)
    water_cell = openmc.Cell(name="water", region=+outer & boundary, fill=water)
    geometry = openmc.Geometry([fuel_cell, clad_cell, water_cell])

    settings = openmc.Settings()
    settings.run_mode = "eigenvalue"
    settings.batches = params["batches"]
    settings.inactive = params["inactive_batches"]
    settings.particles = params["particles"]
    settings.temperature = {"default": params["temperature_K"], "method": "nearest"}
    half = params["pitch_cm"] / 2
    settings.source = openmc.IndependentSource(
        space=openmc.stats.Box([-half, -half, -1.0], [half, half, 1.0])
    )

    materials = openmc.Materials([fuel, clad, water])
    return openmc.Model(geometry=geometry, materials=materials, settings=settings)
