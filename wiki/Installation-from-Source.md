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
