# KiMecO: Kinetic Mechanism Optimizer


<p>
    <img src="graphics/kmo_logo_color.png" width="220" />
</p>

## Description

KiMecO is a kinetic mechanism optimizer. It aims at optimizing chemical kinetic
mechanisms' parameters to allow a generalization of their parameters. It is a
workflow that starts from a set of Master Equation (ME) parameters assembled in a
MESS input. This initial set is perturbed X times to create a generation of models
that all undergo a ME calculation. The resulting rate coefficients and the knowledge
of the corresponding reactions are included in a mechanism file. The latter is used
in Cantera simulations designed to be compared with experimental concentration
profiles. The models are then scored according to the agreement of their simulations
with the experimental data. Using a tournament style genetic algorithm, the winners
are selected and their set of Master Equation parameters is perturbed to produce the
next generation.

If you are using this tool in scientific publications, please reference the
following publication(s):

Submitted.
<!-- TODO: add the KiMecO reference and BibTeX entry once published. -->

We appreciate if you send us the DOI of your published paper that used KiMecO, so we
can feature it here below.

## How to Install

KiMecO is currently installed from source by cloning this repository and installing
it locally. It additionally relies on the MESS master-equation code, which must be
installed separately.

> **Note**
> KiMecO only works with Python >= 3.10.

### From GitHub

A dedicated conda environment is recommended to avoid conflicts with other Python
projects:

```bash
conda create -n kimeco -c conda-forge python=3.10 -y
conda activate kimeco
```

Clone the project from GitHub:

```bash
git clone git@github.com:csoulie/KiMecO.git
```

and then, from within the KiMecO directory produced after cloning, type:

```bash
pip install -e .
```

You can verify the Python-side installation with:

```bash
which kmo
```

### Faster dependency solving with mamba (optional)

```bash
conda install -c conda-forge mamba -y
mamba install -c conda-forge --file requirements.txt -y
pip install --no-build-isolation --no-deps -e .
```

### MESS dependency (required)

KiMecO relies on [MESS](https://github.com/Auto-Mech/MESS) for master-equation
calculations. Build or obtain the static MESS binaries separately, then copy them
into the conda environment binary directory (on Linux, typically `$CONDA_PREFIX/bin`).
You can check whether MESS is available with:

```bash
which mess
```

## How to Run

First, build an input file (e.g. `input.json`). The easiest way is the input-builder
GUI:

```bash
kmo_start
```

To launch an optimization run:

```bash
kmo input.json
```

To inspect the results of a completed run with the analysis GUI:

```bash
kmoui input.json
```

To run the postprocessing utility (e.g. extrapolation to new T, P conditions):

```bash
kmopp input.json
```

You can find additional keywords and options in the documentation.

## Documentation

See the [wiki](https://github.com/csoulie/KiMecO/wiki) for the full list of input
keywords, outputs, and workflow details. The same content is also available in
[MANUAL.md](MANUAL.md).

## List of files in this project

See the repository structure and [MANUAL.md](MANUAL.md) for a description of the
inputs, outputs, and databases produced by KiMecO.

## Authors

* Clément Soulié ([clement.soulie31@gmail.com](mailto:clement.soulie31@gmail.com))

## Papers using KiMecO

<!-- TODO: list publications that used KiMecO here. -->

We appreciate if you send us the DOI of your published paper that used KiMecO, so we
can feature it here.

## Acknowledgement

Copyright (c) 2026 National Technology & Engineering Solutions of Sandia, LLC (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights in this software.

KiMecO is developed and maintained by Clément Soulié under the supervision of Lenny Sheps and Judith Zador.
CS thanks SNL and DOE for funding and support.
<!-- TODO: add funding sources and institutional acknowledgements here. -->
