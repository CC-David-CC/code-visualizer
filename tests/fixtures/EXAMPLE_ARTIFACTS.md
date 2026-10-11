# Example artifact regression fixture

`example-artifacts.json` preserves the 183 existing generated reference outputs
for the 17 saved educational projects. It was captured from the active source
workspace's example outputs when preparing this standalone repository.

`test_examples_progression.py` compares these immutable references with generation
from each saved native project. Keeping one fixture makes that regression check
independent of ignored `examples/projects/*/generated/` build folders.

When intentionally changing generation, review the reference changes together
with the corresponding source/model changes before updating this fixture.
