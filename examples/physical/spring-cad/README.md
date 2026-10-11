# Spring-driven perforated beam

This is native authored source. It contains the equation `F = k*x`, a solve
request, the relevant immutable unit vocabulary, and a Python recipe with stable
parameter/frame/box/cut/publication operation identities. It contains no generated
geometry, live native objects or copied executable result.

Install `requirements-cad.txt` in the application's Python environment. Open
`project.json`, or choose the corresponding File > Physical examples entry.
Follow [the artifact workflow](../../../docs/CAD_ARTIFACT_WORKFLOW.md) to freeze
the spring solve, bind its exact solution to Python, publish the solid, create
independent measurement/mesh consumers, or promote a retained solid to an
independent translation input.

For a reproducible command-line proof using this saved source:

```powershell
python tools/prove_cad_artifacts.py --output .test-cad-proof
```

Use a fresh output directory. The proof uses the ordinary computation host and
native command journal, closes producer hosts between steps, and replays portable
consumer plans. It writes verified resources, evidence, native authoring history
and `cad-proof.json`. It does not invoke this example's construction factory.
Real dirty-Git concurrency/recovery is covered separately by
`tests/test_cad_experiments.py` and the preserved P2 regression gates.

Expected geometry: 50 × 20 × 10 mm with a 2 mm radius through-hole, volume
`9.874336293856409e-6 m³`. Force 12 N instead of 10 N gives a new 60 mm solid.
The display mesh is a distinct typed resource; face indices are scoped to its
parent geometry hash. The initial frame is explicitly right-handed Cartesian
with millimeter coordinates, owned by the authored Python recipe.
