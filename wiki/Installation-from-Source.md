# Installation from source

These instructions are written for users who are not familiar with command-line tools.

## 1) Create a dedicated conda environment

Using a dedicated environment avoids conflicts with other Python projects.

```bash
conda create -n kimeco -c conda-forge python=3.10 -y
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
- Build or obtain the static MESS binaries separately.
- The static binaries should be manually copied into the conda environment binary directory.

On Linux, this is typically:

```bash
$CONDA_PREFIX/bin
```

Once copied there, the MESS executables are available from the active conda environment. You can check whether MESS is available by running:

```bash
which mess
```

## 6) automech dependency (optional)

`automech` (which provides `autoio`/`mess_io`) is an **optional** dependency needed only when you enable the conditional two-pass MESS WellExtension path with `use_automech=true`. When `use_automech=false` (the default), automech is not imported and does not need to be installed.

- automech can be obtained from GitHub: https://github.com/Auto-Mech/autochem (and related Auto-Mech packages).
- If you set `use_automech=true`, `mess_io` must be importable in **both** the run environment and the job (compute-node) environment; otherwise KiMecO cancels the run early with a clear message.
- If you set `use_automech=true`, **KiMecO itself (`kimeco`) must also be importable in the job (compute-node) environment**, not only in the run environment: the emitted per-PES driver imports `kimeco.readers.mess_output.MessOutputReader` to decide whether MESS pass 2 is needed. The import is side-effect-free (no database connection), but the compute node must be able to resolve KiMecO's dependency chain. In practice, install KiMecO in the same environment the jobs activate.
