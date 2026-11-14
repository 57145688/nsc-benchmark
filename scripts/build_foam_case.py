"""Write a 2D axisymmetric OpenFOAM case for the RPV natural circulation loop.

The case is deliberately a reduced model: a porous core (heat source), a porous
steam-generator region (heat sink) and an annular downcomer separated by a
porous barrel.  It uses the radial power distribution from ``results/core``
and writes everything as plain text so it can be regenerated per iteration.
"""

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RHO0 = 750.0  # kg/m3, Boussinesq reference density
CP = 5500.0  # J/kg/K
WEDGE_DEG = 5.0
SECTOR = WEDGE_DEG / 360.0  # the wedge is 1/72 of the full loop
R0 = 0.05  # m, central hole; keeps the azimuthal cell size (r*dtheta) reasonable
R_RPV = 1.2255  # m, RPV inner wall (fluid domain outer radius)
Z_BOTTOM = -0.4
Z_TOP = 10.5
CORE_Z = (0.2, 2.4)
# Integral-PWR layout: hot riser in the centre, steam generator on the
# down-flowing annulus, cold downcomer outside it.  Putting the SG above the
# core makes the cooled fluid gravitationally unstable and reverses the loop.
RISER_Z = (2.4, 8.0)
CORE_RADIUS = 0.94  # fill to the riser shroud: no core bypass gap
SHROUD_RADII = (0.94, 0.96)
SG_Z = (4.0, 8.0)
SG_RADII = (0.96, 1.2255)  # full annulus: no parallel bypass outside the SG
DOWNCOMER_RADII = (0.96, 1.2255)  # below the SG, same annulus
RINGS = [0.15, 0.35, 0.55, 0.85]


HEADER = """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v1912                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       {cls};
    object      {obj};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as handle:
        handle.write(text)


def block_mesh():
    angle = math.radians(WEDGE_DEG / 2.0)
    vertices = []
    for z in (Z_BOTTOM, Z_TOP):
        for radius, theta in (
            (R0, -angle),
            (R_RPV, -angle),
            (R_RPV, angle),
            (R0, angle),
        ):
            vertices.append(
                (radius * math.cos(theta), radius * math.sin(theta), z)
            )
    text = HEADER.format(cls="dictionary", obj="blockMeshDict")
    text += "\nscale 1;\n\nvertices\n(\n"
    for vertex in vertices:
        text += f"    ({vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f})\n"
    text += """
);

blocks
(
    hex (0 1 2 3 4 5 6 7) (90 1 300) simpleGrading (1 1 1)
);

edges
();

boundary
(
    axis
    {
        type slip;
        faces ((0 3 7 4));
    }
    outerWall
    {
        type wall;
        faces ((1 2 6 5));
    }
    bottom
    {
        type wall;
        faces ((0 1 2 3));
    }
    top
    {
        type wall;
        faces ((4 5 6 7));
    }
    front
    {
        type wedge;
        faces ((0 1 5 4));
    }
    back
    {
        type wedge;
        faces ((3 2 6 7));
    }
);

mergePatchPairs
();

// ************************************************************************* //
"""
    return text


def fields():
    axis_slip = "type slip;"
    wall = "type noSlip;"
    scalar_wall = "type zeroGradient;"

    u = HEADER.format(cls="volVectorField", obj="U") + f"""
dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{{
    axis        {{ {axis_slip} }}
    outerWall   {{ {wall} }}
    bottom      {{ {wall} }}
    top         {{ {wall} }}
    front       {{ type wedge; }}
    back        {{ type wedge; }}
}}
"""
    p = HEADER.format(cls="volScalarField", obj="p") + """
dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    axis        { type calculated; value uniform 0; }
    outerWall   { type calculated; value uniform 0; }
    bottom      { type calculated; value uniform 0; }
    top         { type calculated; value uniform 0; }
    front       { type wedge; }
    back        { type wedge; }
}
"""
    p_rgh = HEADER.format(cls="volScalarField", obj="p_rgh") + """
dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    axis        { type fixedFluxPressure; rho rhok; value uniform 0; }
    outerWall   { type fixedFluxPressure; rho rhok; value uniform 0; }
    bottom      { type fixedFluxPressure; rho rhok; value uniform 0; }
    top         { type fixedFluxPressure; rho rhok; value uniform 0; }
    front       { type wedge; }
    back        { type wedge; }
}
"""
    t = HEADER.format(cls="volScalarField", obj="T") + f"""
dimensions      [0 0 0 1 0 0 0];

internalField   uniform 560;

boundaryField
{{
    axis        {{ {scalar_wall} }}
    outerWall   {{ {scalar_wall} }}
    bottom      {{ {scalar_wall} }}
    top         {{ {scalar_wall} }}
    front       {{ type wedge; }}
    back        {{ type wedge; }}
}}
"""
    nut = HEADER.format(cls="volScalarField", obj="nut") + """
dimensions      [0 2 -1 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    axis        { type calculated; value uniform 0; }
    outerWall   { type calculated; value uniform 0; }
    bottom      { type calculated; value uniform 0; }
    top         { type calculated; value uniform 0; }
    front       { type wedge; }
    back        { type wedge; }
}
"""
    alphat = HEADER.format(cls="volScalarField", obj="alphat") + """
dimensions      [0 2 -1 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    axis        { type calculated; value uniform 0; }
    outerWall   { type calculated; value uniform 0; }
    bottom      { type calculated; value uniform 0; }
    top         { type calculated; value uniform 0; }
    front       { type wedge; }
    back        { type wedge; }
}
"""
    return {"U": u, "p": p, "p_rgh": p_rgh, "T": t, "nut": nut, "alphat": alphat}


def topo_set():
    def cylinder(name, radius, z0, z1):
        return f"""    {{
        name {name};
        type cellSet;
        action new;
        source cylinderToCell;
        p1 (0 0 {z0});
        p2 (0 0 {z1});
        radius {radius};
    }}
    {{
        name {name};
        type cellZoneSet;
        action new;
        source setToCellZone;
        set {name};
    }}
"""

    def box(name, x0, x1, z0, z1):
        return f"""    {{
        name {name};
        type cellSet;
        action new;
        source boxToCell;
        box ({x0} -0.2 {z0}) ({x1} 0.2 {z1});
    }}
    {{
        name {name};
        type cellZoneSet;
        action new;
        source setToCellZone;
        set {name};
    }}
"""

    actions = cylinder("core", CORE_RADIUS, *CORE_Z)
    actions += box("sg", SG_RADII[0], SG_RADII[1], *SG_Z)
    actions += box("shroud", SHROUD_RADII[0], SHROUD_RADII[1], 0.0, SG_Z[1])
    for index, outer in enumerate(RINGS, start=1):
        inner = 0.0 if index == 1 else RINGS[index - 2]
        actions += box(f"coreRing{index}", inner, outer, *CORE_Z)
    return HEADER.format(cls="dictionary", obj="topoSetDict") + f"""
actions
(
{actions});

// ************************************************************************* //
"""


def set_fields():
    return HEADER.format(cls="dictionary", obj="setFieldsDict") + """
defaultFieldValues
(
    volScalarFieldValue T 560
);

regions
(
    cellToCell
    {
        set core;
        fieldValues
        (
            volScalarFieldValue T 575
            volVectorFieldValue U (0 0 0.05)
        );
    }
);

// ************************************************************************* //
"""


def fv_options(ring_power_w):
    """Heat source/sink and porous zones.

    ``ring_power_w`` must already be the power released *inside the wedge*
    (full-core ring power times the sector fraction), because the denominator
    is the wedge volume.  Mixing the two is a factor-72 error.
    """
    sector = SECTOR
    core_volume = math.pi * (CORE_RADIUS**2 - R0**2) * (CORE_Z[1] - CORE_Z[0]) * sector
    sg_volume = (
        math.pi
        * (SG_RADII[1] ** 2 - SG_RADII[0] ** 2)
        * (SG_Z[1] - SG_Z[0])
        * sector
    )
    total_power = sum(ring_power_w.values())

    entries = []
    for index in sorted(ring_power_w):
        inner = R0 if index == 1 else RINGS[index - 2]
        outer = RINGS[index - 1]
        volume = (
            math.pi
            * (outer**2 - inner**2)
            * (CORE_Z[1] - CORE_Z[0])
            * sector
        )
        source = ring_power_w[index] / volume / (RHO0 * CP)
        entries.append(
            f"""    coreHeat{index}
    {{
        type            scalarSemiImplicitSource;
        selectionMode   cellZone;
        cellZone        coreRing{index};
        volumeMode      specific;
        injectionRateSuSp
        {{
            T           ({source:.6f} 0);
        }}
    }}
"""
        )

    sink = -total_power / sg_volume / (RHO0 * CP)
    entries.append(
        f"""    sgHeatSink
    {{
        type            scalarSemiImplicitSource;
        selectionMode   cellZone;
        cellZone        sg;
        volumeMode      specific;
        injectionRateSuSp
        {{
            T           ({sink:.6f} 0);
        }}
    }}
"""
    )

    entries.append(
        """    corePorosity
    {
        type            explicitPorositySource;
        explicitPorositySourceCoeffs
        {
            selectionMode   cellZone;
            cellZone        core;
            type            DarcyForchheimer;
            d               (2e6 2e6 2e6);
            f               (0 0 0);
            coordinateSystem
            {
                type    cartesian;
                origin  (0 0 0);
                e1      (1 0 0);
                e2      (0 1 0);
            }
        }
    }
    sgPorosity
    {
        type            explicitPorositySource;
        explicitPorositySourceCoeffs
        {
            selectionMode   cellZone;
            cellZone        sg;
            type            DarcyForchheimer;
            d               (1e6 1e6 1e6);
            f               (0 0 0);
            coordinateSystem
            {
                type    cartesian;
                origin  (0 0 0);
                e1      (1 0 0);
                e2      (0 1 0);
            }
        }
    }
    shroudBlockage
    {
        type            explicitPorositySource;
        explicitPorositySourceCoeffs
        {
            selectionMode   cellZone;
            cellZone        shroud;
            type            DarcyForchheimer;
            d               (1e10 1e10 1e10);
            f               (0 0 0);
            coordinateSystem
            {
                type    cartesian;
                origin  (0 0 0);
                e1      (1 0 0);
                e2      (0 1 0);
            }
        }
    }
"""
    )

    return HEADER.format(cls="dictionary", obj="fvOptions") + "\n".join(entries) + (
        "\n// ************************************************************************* //\n"
    )


def constant_files():
    g = HEADER.format(cls="uniformDimensionedVectorField", obj="g") + """
dimensions      [0 1 -2 0 0 0 0];
value           (0 0 -9.81);
"""
    transport = HEADER.format(cls="dictionary", obj="transportProperties") + """
transportModel  Newtonian;

nu              1.3e-07;
beta            2.45e-03;
TRef            560;
Pr              1.5;
Prt             0.85;
"""
    turbulence = HEADER.format(cls="dictionary", obj="turbulenceProperties") + """
simulationType  laminar;
"""
    return {"g": g, "transportProperties": transport, "turbulenceProperties": turbulence}


def system_files(end_time=150.0, max_delta_t=0.5, write_interval=30.0):
    control = HEADER.format(cls="dictionary", obj="controlDict") + f"""
application     buoyantBoussinesqPimpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {end_time};
deltaT          0.001;
adjustTimeStep  yes;
maxCo           10.0;
maxDeltaT       {max_delta_t};
writeControl    runTime;
writeInterval   {write_interval};
purgeWrite      20;
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
"""
    schemes = HEADER.format(cls="dictionary", obj="fvSchemes") + """
ddtSchemes      { default Euler; }
gradSchemes     { default Gauss linear; }
divSchemes
{
    default         none;
    div(phi,U)      Gauss upwind;
    div(phi,T)      Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes   { default corrected; }
wallDist        { method meshWave; }
"""
    solution = HEADER.format(cls="dictionary", obj="fvSolution") + """
solvers
{
    p_rgh
    {
        solver          PCG;
        preconditioner  DIC;
        tolerance       1e-07;
        relTol          0.01;
    }
    p_rghFinal
    {
        solver          PCG;
        preconditioner  DIC;
        tolerance       1e-07;
        relTol          0;
    }
    "(U|T)"
    {
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-06;
        relTol          0.1;
    }
    "(U|T)Final"
    {
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-06;
        relTol          0;
    }
}

PIMPLE
{
    momentumPredictor   no;
    nOuterCorrectors    1;
    nCorrectors         2;
    nNonOrthogonalCorrectors 1;
    pRefCell            0;
    pRefValue           0;
}

relaxationFactors
{
    fields
    {
        p_rgh   0.7;
    }
    equations
    {
        U       0.7;
        T       0.7;
    }
}
"""
    return {
        "controlDict": control,
        "fvSchemes": schemes,
        "fvSolution": solution,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--power", default=os.path.join(HERE, "results", "core", "power.json"))
    parser.add_argument("--case", default=os.path.join(HERE, "results", "foam", "case"))
    parser.add_argument("--end-time", type=float, default=150.0)
    parser.add_argument("--max-delta-t", type=float, default=0.5)
    parser.add_argument("--write-interval", type=float, default=30.0)
    parser.add_argument(
        "--power-scale",
        type=float,
        default=1.0,
        help="fraction of the rated core power represented by the full loop",
    )
    args = parser.parse_args(argv)

    with open(args.power) as handle:
        power = json.load(handle)

    # Full-loop ring power, then the share released inside the 5 degree wedge.
    full_ring_power_w = {
        ring["ring"]: float(ring["power_w"]) * args.power_scale
        for ring in power["rings"]
    }
    ring_power_w = {
        index: value * SECTOR for index, value in full_ring_power_w.items()
    }

    case = os.path.abspath(args.case)
    write(os.path.join(case, "system", "blockMeshDict"), block_mesh())
    write(os.path.join(case, "system", "topoSetDict"), topo_set())
    write(os.path.join(case, "system", "setFieldsDict"), set_fields())
    for name, text in system_files(
        args.end_time, args.max_delta_t, args.write_interval
    ).items():
        write(os.path.join(case, "system", name), text)
    for name, text in constant_files().items():
        write(os.path.join(case, "constant", name), text)
    write(os.path.join(case, "constant", "fvOptions"), fv_options(ring_power_w))
    for name, text in fields().items():
        write(os.path.join(case, "0", name), text)

    total = sum(ring_power_w.values())
    full_total = sum(full_ring_power_w.values())
    info = {
        "total_power_w": total,
        "full_loop_power_w": full_total,
        "power_scale": args.power_scale,
        "sector_fraction": SECTOR,
        "rated_core_power_w": power["thermal_power_mw"] * 1e6,
        "core_volume_m3": math.pi
        * (CORE_RADIUS**2 - R0**2)
        * (CORE_Z[1] - CORE_Z[0])
        * SECTOR,
        "ring_power_w": ring_power_w,
        "ring_source_K_per_s": {
            ring["ring"]: ring_power_w[ring["ring"]]
            / (
                math.pi
                * (RINGS[ring["ring"] - 1] ** 2 - (R0 if ring["ring"] == 1 else RINGS[ring["ring"] - 2]) ** 2)
                * (CORE_Z[1] - CORE_Z[0])
                * SECTOR
            )
            / (RHO0 * CP)
            for ring in power["rings"]
        },
        "rho0": RHO0,
        "cp": CP,
        "end_time_s": args.end_time,
        "max_delta_t_s": args.max_delta_t,
    }
    write(os.path.join(case, "case_info.json"), json.dumps(info, indent=2))
    print(f"wrote OpenFOAM case to {case}")
    print(
        f"  full-loop power {full_total/1e6:.1f} MW, "
        f"wedge power {total/1e6:.3f} MW, core volume {info['core_volume_m3']:.4f} m3"
    )
    for index in sorted(ring_power_w):
        print(
            f"  ring {index}: {ring_power_w[index]/1e3:.1f} kW in wedge, "
            f"source {info['ring_source_K_per_s'][index]:.3f} K/s"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
