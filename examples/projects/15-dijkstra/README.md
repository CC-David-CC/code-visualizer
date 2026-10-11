# 15 · Dijkstra and A* Pathfinding

Two source-mapped heap-frontier algorithms with deterministic graph tests.

Open this directory from Code Visualizer. The canonical editable model is `project.json`; `generated/` is a complete manifest-backed artifact set. Use document editors for programming examples, or the Domain Workbench for domain examples. Save and generate the project, or use the live Run/Trace/Debug controls in the relevant editor.


## Runtime visualization walkthrough

Choose **My Lens | Pathfinding conceptual core** to compare Dijkstra and A*. Start Debug on the runnable main diagram, then leave the visualizer on **Control flow** or **Data flow**: runtime is an overlay on every lens. Focus `frontier`, inspect it as **Heap**, and step to see the active DRAKON node, incoming route, changed symbol, and heap mutation. Previous/Next/Live recompute the same overlays for bounded history without rewinding or mutating the program.
