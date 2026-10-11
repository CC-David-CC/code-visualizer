# Start Code Visualizer

This folder contains the complete Code Visualizer source release. It does not need a
custom Windows executable.

Requirements:

- Python 3.12 or newer on PATH;
- about 1.5 GB free for the first local environment;
- Windows x64 with Python 3.12 or 3.13 can install entirely from the included
  `wheels/` directory.

Launch the desktop:

```text
python launch.py
```

The first run creates `.runtime/` inside this folder, installs the pinned dependencies,
then opens the desktop. Later runs reuse that environment. Nothing is installed
globally.

Useful commands:

```text
python launch.py --cli --help
python launch.py --cli --version
python launch.py --launcher-help
```

On another supported platform, use `python launch.py --online` if the bundled Windows
wheels are not compatible. Runtime versions are pinned in `requirements.txt`;
development/test versions are pinned in `requirements-dev.txt`.

Read `docs/QUICKSTART.md` for Hello World and `STATUS.md` for exact verification
evidence. The application is local-first. Opening, saving, validating, and generating
do not execute project Python; Run, Trace, and Debug are explicit local execution
boundaries.
