# First physical domain: finite DC networks

`org.codevisualizer.electrical.dc@1` owns Circuit, Net, Terminal, Resistor and
VoltageSource intentions. A component owns one positive and one negative
terminal. Each terminal references exactly one net in its circuit. Connectivity
has one owner; graph links and table cells do not duplicate endpoint meaning.
The circuit identifies a reference net and declares its unit vocabulary.

The domain has a connectivity graph, resistor table, terminal-connection table
and hierarchy/form. These are ordinary notation contributions over the same
identities. Parameters are quantities with declared dimensions. Resistance and
characteristic scales must be positive finite real values. An incompatible
physical unit is rejected by schema value constraints before numerical work.

The `org.codevisualizer.electrical.dc.equations@1` transformation derives math@2:

- One potential symbol per net, with the circuit's voltage scale and output unit.
- One current symbol per component, oriented from its positive to negative terminal.
- A resistor relation V(positive)-V(negative)=R*I.
- An ideal source relation V(positive)-V(negative)=the authored source voltage.
- An explicit zero-potential equation for the chosen reference.
- Current conservation at each other net. Reference-net conservation is dependent.

The circuit's current and voltage scales become variable and residual scales in
the shared equation contract. Defaults are 1 V and 0.001 A. Authoring equivalent
scales in mA changes reported units without changing the physical solution.
No circuit formula, component case or connectivity rule exists in the general
compiler or numerical backend.

Derived identities use the registered transformation key, source identity and
semantic role. Names and source collection order do not choose equations or IDs.
Every derived object maps back to circuit, net, component or terminal identities.
Derived mathematical models remain disposable and are never journaled as authored
contents. Their references resolve against the frozen input context; generated
ownership is checked for collisions before combined structural validation.

The initial headless proof checks the 5 V/1000 ohm divider at 2.5 V, the additional
1000 ohm load at 5/3 V, branch/source currents, normalized conservation residuals
and origins. A distinct five-resistor bridge checks topology independently:
nodal equations 17L-2R=100 and -12L+47R=200 give L=204/31 V, R=184/31 V,
bridge current 1/775 A and source current -37/775 A.

This is an ideal finite DC contract. It does not claim AC, nonlinear devices,
transient simulation, distributed electromagnetic effects or CAD. The existing
host, resources, evidence, Git experiment history and edit authority supply those
general workbench boundaries; the physical extension does not replace them.
