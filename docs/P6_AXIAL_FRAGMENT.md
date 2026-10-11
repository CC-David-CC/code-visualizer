# P6 axial adapter: declared initial fragment

Status: numerical, workbench and release qualification repeated after shared
compiler correction P6-R1. P6 acceptance remains pending user review. See
[the current acceptance map](P6_ACCEPTANCE_MAP.md) and
[correction record](P6_R1_CORRECTION.md). The axial domain itself is unchanged.

This is the independent P6-05 client
of P3 equations, P4 CAD and the existing resource/computation host.

The authored definition owns a material, geometry idealization, one fixed axial
support and one signed axial resultant. Both boundary conditions reference the
ordinary P4 `RegionSelection` intentions on one exact BREP. Replacing geometry
requires explicit selection updates and geometric re-resolution. No naked face
index is an authored boundary condition. A generated mapping records resolved
face indices together with their exact parent hash and original CAD provenance.

The supported solid is a valid single Cartesian rectangular prism with six filled
planar rectangular faces, twelve straight edges and eight distinct corners.
Topology, face normals and areas, material volume and endpoints are verified.
Bounding-box dimensions alone cannot establish a material section. Holes, taper,
disconnected bodies, transverse loads and general 3D elasticity remain unsupported.

The declared geometry tolerance is 1e-7 relative to size and 1e-9 m absolute;
native origin offsets do not enlarge the tolerance. Coordinates use the exact
resource frame and unit. BREP admission is bounded to 64 MiB. Material modulus
is finite in 1..1e15 Pa, signed force magnitude at most 1e9 N, and the qualified
linear fragment admits at most 1% axial strain. One fixed end and 3..65 nodes
produce 2..64 linear elements. No automatic remeshing or nonlinear fallback.

Each actual element contributes EA/l times [[1,-1],[-1,1]]. The reduced assembled
equilibrium is solved through P3's scaled, rank/condition/residual-checked linear
boundary. Force residual scale is max(1 N, absolute applied force), displacement
scale 1e-5 m, rank threshold 1e-12, condition ceiling 1e12, and normalized residual
ceiling 1e-10. These are numerical solve criteria, separate from geometry criteria.

Independent analytical checks use FL/(EA), F/A, reaction -F and energy F²L/(2EA),
with relative tolerance 1e-8 and absolute tolerance 1e-12 in each specified SI
output unit. The 0.1 m by 0.01 m by 0.01 m, 200 GPa, 1000 N fixture must give
5e-6 m extension, 1e7 Pa stress, -1000 N reaction and 0.0025 J energy. A separate
nonuniform two-element assembly check does not broaden the supported BREP shape.

Mapping and result metadata have separate exact version-1 resource contracts.
Coordinates, displacement, stress, element forces, full stiffness and load arrays
carry explicit SI units and reuse bounded P5 numeric resources. Native shapes,
generated meshes and solved displacement are disposable derived data. Execution
uses the normal backend and artifact/portable closure; CAD is produced by the
existing emitted Python package, not another CAD execution path.

At source `208e754`, all 37 distinct focused cases pass on Windows with the
50% process-tree CPU cap, including 28 new structural cases and nine unchanged
CAD/dependency gates. The four declared resolutions pass through real authority
transactions, frozen preparation, native geometry and P3 computation. Source
lint and typing pass for 344 files. Raw earlier failures are retained: a runtime
annotation import and incorrect calls in the new SDK test fixture. The source-
bound increment receipt is `phase-records/p6-20260913/axial-receipt.json` in Git.
