# Performance and scale

The deterministic M9 fixture contains 500 DRAKON diagrams, one 300-atom diagram, a
341,047-byte native snapshot, and 15,547 generated Python characters. Its semantic
index gate separately uses 500 diagrams with 20 atoms each (10,000 operations). Run it
with:

```powershell
.venv\Scripts\python tools\benchmark_scale.py
```

Reference run: Windows 11 build 26200, Surface Book 2, 15.9 GiB RAM, Intel64 family 6
model 142, Python 3.13.15. Exact machine-readable evidence is in
[`artifacts/performance/m9-scale-results.json`](../artifacts/performance/m9-scale-results.json).

| Operation | Seconds |
|---|---:|
| Native save | 0.0292 |
| Native open/recovery | 0.1219 |
| Project search | 0.0019 |
| Validation | 0.0109 |
| Semantic index, 500 x 20 atoms | 2.8598 |
| Python generation in memory | 0.0979 |
| Layout of 300 atoms | 0.0153 |
| GUI open of 500-diagram project | 0.6799 |

The semantic workload produces 74,003 objects and 105,502 relations. Its release test
has a deliberately generous 12-second CI budget. Direct canonical indexing and the
live-document early return remove the prior per-document copy/filter hotspot.

The project tree is complete immediately, while only one of 500 document widgets is
materialized initially. Selecting a distant diagram lazily creates its editor. This
removed the previous 44.70-second eager 500-tab startup.

Validation and disk generation use worker threads and publish revision-aware states
to Qt. Child output and trace history are bounded; the visible consoles retain at most
their configured line count. Authority event replay and journals are bounded and
fall back to snapshot resynchronization/compaction rather than growing without limit.

Performance tests use real persistence, validation, canonical semantic indexing,
generation, layout, search, GUI construction, and project-tree activation. Thresholds are intentionally generous
enough for CI variance while catching accidental eager widget creation or algorithmic
regressions.
