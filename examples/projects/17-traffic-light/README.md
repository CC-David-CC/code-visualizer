# 17 · Traffic Light Domain Workbench

One state machine edited through graph, table, and form with runtime origins.

Open this directory from Code Visualizer. The canonical editable model is `project.json`; `generated/` is a complete manifest-backed artifact set. Use document editors for programming examples, or the Domain Workbench for domain examples. Save and generate the project, or use the live Run/Trace/Debug controls in the relevant editor.


## One state machine, three editable notations

Open **Domain Workbench** and select **Traffic Light**. The graph, transition table, and hierarchy share the same state, transition, event, and action IDs. In the table, rename Yellow to Amber through the Target cell of the Green transition. The graph, form, semantic search, and generated Python immediately read the same renamed object. Undo and redo preserve its identity.

Use **Trace** to execute the default three timer events, or **Debug** and step through transitions. Runtime highlights refer back to the original states, transitions, and message actions in every notation. The generated program and origin map are disposable build artifacts; `project.json` contains the domain schema, canonical intentions, and typed language definitions.

## Edit the language itself

Select **Language authoring > Edit definition** to inspect and change the notations, validation rules, and transformation templates. The finite-state-machine behavior in this example is interpreted from these saved definitions; it does not use the handwritten FSM extension. The structured editor offers typed node choices, property/role selectors, bindings, symbols, and ordered template bodies. Save, build, and trace after a change; undo restores the prior language definition. The **Transition sentences** notation shows editable state names and transition sentences using the general composition language. Select that notation in the definition editor and choose **Edit notation expression and preview** to invent a different layout. Query slots also offer **Edit query expression** for readable validator and transformation expressions over the same typed definitions. See `docs/DOMAIN_LANGUAGE.md` and `docs/WORKBENCH_AUTHORING.md` in the source folder.
