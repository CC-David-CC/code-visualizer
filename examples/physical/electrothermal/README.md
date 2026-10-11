# Resistor and heat sink

This saved source contains an authored DC circuit, two thermal bodies, a
temperature-dependent resistance law, signed heat exchange and a fixed-window
policy. It is a synthetic, bounded electrothermal example: 5 V, 10 ohm at
293.15 K, two heat capacities and a path to ambient. The 100-second transient
uses one-second backward-Euler windows. This is not a calibrated device model.

Open **File → Physical examples → Resistor and heat sink**, or open this folder.
In **Domain Workbench**, select the electrothermal experiment. Its form exposes
the bodies, resistance law, conductances, temperature points and numerical/output
policy. The circuit model exposes the source voltage and its typed terminals.
Use **Apply fields** to accept an edit; undo/redo preserve object identities.

Save to your Git project, select **Coupled electrothermal backward Euler**, and
choose **Freeze & Run**. The existing experiment controls retain the source
commit and attempt before admitting execution. The next accepted semantic edit
creates a new unrun variant; it never changes the old run's input.

In **Computation and evidence → Channels, time and trials**:

- Choose resistor/sink temperature, current, Joule power, contact heat or energy.
- Scrub the exact retained samples or play them at your chosen display rate.
- Inspect all channels at that same time in the table. Temperature points are
  explicitly labelled; watts and joules remain different quantities.
- Inspect provisional iterations separately. Their numerical base can be newer
  than the retained prefix. A trial never advances the retained history cursor.
- Select a channel's source object, or **Create exact probe** to author a new
  consumer of that resource, channel identity and exact sample time.

Cancel through the existing computation control. The outcome stays cancelled
even if useful complete samples were retained. In the experiment's checkpoint
controls, explicitly select a compatible retained checkpoint and resume in a new
attempt. Changing physics or the frozen method/schedule requires a new run.

The independent proof tool is `tools/prove_coupled_physics.py`. It loads this
JSON with example-factory imports forbidden, compares decoded samples with an
independently derived discrete reference, consumes copied history after producer
exit and checks exact restart parity. Full continuous-reference/refinement and
failure/Git tests remain part of normal pytest qualification.
