# Installation from source

These instructions are written for users who are not familiar with command-line tools.

## 1) Create a dedicated conda environment

Using a dedicated environment avoids conflicts with other Python projects.

```bash
conda create -n kimeco -c conda-forge python=3.11 pip -y
conda activate kimeco
```

After activation, your terminal prompt usually shows `(kimeco)`.

## 2) Install KiMecO

From the repository root, run:

```bash
pip install -e .
```

Yes: in most cases this simple command works after creating the environment.

## 3) Optional: faster dependency solving with mamba

Recommended method (faster dependency solving):

```bash
conda install -c conda-forge mamba -y
mamba install -c conda-forge --file requirements.txt -y
```

Then install KiMecO:

```bash
pip install --no-build-isolation --no-deps -e .
```

This optional route is mainly useful if you want conda-forge builds for dependencies.

## 4) Verify installation

Run one or more of the following commands:

```bash
which kmo
```

If `which kmo` returns a path and the `--help` commands print help messages, the Python-side installation is working.

## 5) MESS dependency (required)

KiMecO relies on MESS for master-equation calculations.

- MESS can be downloaded from GitHub: https://github.com/Auto-Mech/MESS
- The recommended route is the pre-built static binary package from the `auto-mech` conda channel. With the environment activated, run:

```bash
conda install -c auto-mech mess-static -y
```

- Fallback: build or obtain the static MESS binaries separately and copy them manually into the conda environment binary directory. On Linux, this is typically:

```bash
$CONDA_PREFIX/bin
```

Once installed (or copied there), the MESS executables are available from the active conda environment. You can check whether MESS is available by running:

```bash
which mess
```

It must print a path inside the active environment (e.g. `.../envs/kimeco/bin/mess`); if it prints nothing or a path outside the environment, MESS is not installed where KiMecO will look for it.

## 6) automech dependency (optional)

`automech` is an **optional** dependency needed only when you enable the two-pass MESS WellExtension path with `use_automech=true`. It provides `mess_io` (from `autoio`) and `phydat` (from `autochem`). When `use_automech=false` (the default), automech is not imported and does not need to be installed.

To install KiMecO together with the automech dependencies, from the repository root run (`autoio` and `autochem` are not published on PyPI, so they are installed from GitHub first):

```bash
pip install "autoio @ git+https://github.com/Auto-Mech/autoio@0.2026.0" "autochem @ git+https://github.com/Auto-Mech/autochem@0.2026.3"
pip install -e .[automech]
```

(`pip install kimeco[automech]` for a non-editable install, after the same `autoio`/`autochem` pre-install.) Alternatively, with conda: `conda install autoio autochem -c auto-mech`.

If you are starting from a fresh environment, the following sequence replaces steps 2 and 5 above (create the environment, install MESS, install `autoio`/`autochem` from GitHub — they are not published on PyPI — then install KiMecO with the automech extra):

```bash
conda create -n kimeco -c conda-forge python=3.11 pip -y
conda activate kimeco
conda install -c auto-mech mess-static -y
pip install "autoio @ git+https://github.com/Auto-Mech/autoio@0.2026.0" "autochem @ git+https://github.com/Auto-Mech/autochem@0.2026.3"
pip install -e .[automech]
python -c "import mess_io, phydat, kimeco"
```

The last command prints nothing when the automech dependencies are importable. Developers who also want the git hooks / `pytest` can use `pip install -e .[automech,test]` instead. Run `which mess` afterwards to confirm the MESS binary resolves inside the environment.

- The minimum Python version is 3.11 with or without the `automech` extra.
- If you set `use_automech=true`, `mess_io` must be importable in **both** the run environment and the job (compute-node) environment; otherwise KiMecO cancels the run early with a message pointing to `pip install kimeco[automech]`.
- If you set `use_automech=true`, **KiMecO itself (`kimeco`) must also be importable in the job (compute-node) environment**, not only in the run environment: the emitted per-PES driver imports `kimeco.readers.mess_output.MessOutputReader` to decide whether MESS pass 2 is needed. The import is side-effect-free (no database connection), but the compute node must be able to resolve KiMecO's dependency chain. In practice, install KiMecO (with the `automech` extra) in the same environment the jobs activate.
