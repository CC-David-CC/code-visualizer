# Solid bar to axial equilibrium

This saved Python-domain recipe publishes a real, filled rectangular CAD bar:
100 mm long, 10 mm wide and 10 mm high, with an explicit space, frame and native
coordinate unit. Its BREP is an immutable derived resource. Material, supports
and loads are authored separately as consumers of the selected solid.

1. Open **File → Physical examples → Solid CAD bar and axial equilibrium**, or
   this folder. Save it to your Git project. In **Artifact inputs and geometry**,
   choose **Freeze Python CAD producer…** and enter required output name `bar`.
   This submits the ordinary Python computation to **Freeze & Run**.
2. Select the `bar` artifact in the evidence inspector. You can create a display
   mesh through the existing CAD controls. The producer process may now exit.
3. Choose **Create axial analysis…**. Enter 200 GPa, 1000 N, nine nodes, and the
   x axis. One authority transaction authors the material, fixed minimum-end
   predicate, loaded maximum-end predicate, load and explicit axial idealization.
   The immutable input resource is retained before that transaction. In a frozen
   editor the operation follows the ordinary fork-before-edit path.
4. Inspect/edit those intentions in the domain form. Select the axial model and
   **Freeze & Run** using **Linear axial bar equilibrium**. The ordinary worker
   checks topology, material section, frame and region predicates, assembles the
   real element equations, and solves them through P3.
5. Inspect the derived result: extension 5e-6 m, stress 1e7 Pa, reaction -1000 N
   and strain energy 0.0025 J. The displacement-versus-coordinate plot scales its
   axes independently; it never replaces or edits the CAD solid.

Equivalent SI/mm coordinates, zero/reversed force and 3–65 nodes are supported.
Holes, taper, disconnected solids, transverse loads and general 3D elasticity
are explicitly outside this fragment. The old perforated beam is not a valid
solid-prism analysis input. The geometry/mapping tolerances and numerical bounds
are in `docs/P6_AXIAL_FRAGMENT.md`.

`tools/prove_coupled_physics.py` executes the saved recipe with factories
forbidden, closes its producer, copies only declared resources, authors a new
independent structural consumer, checks analytical oracles and repeats the
computation from a portable plan in an empty store.
