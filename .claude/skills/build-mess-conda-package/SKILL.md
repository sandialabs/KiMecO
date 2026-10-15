---
name: build-mess-conda-package
description: "Build, and optionally upload, the mess-static conda package that ships prebuilt static MESS binaries for KiMecO. Use when updating or rebuilding conda-recipes/mess-static, bumping its version, pinning the upstream Auto-Mech/MESS git revision, checking the recipe license, or troubleshooting a missing mess executable that should come from the mess-static dependency."
---
# Build the mess-static conda package

## When to use

Rebuilding or updating the `mess-static` package (prebuilt static MESS executables) that KiMecO's own conda recipe depends on, or tracking down why `mess` is missing from an env that installed it.

## Prerequisites

- Linux (the recipe has `skip: true  # [not linux]`).
- `conda-build` installed in a base/build env (`conda install conda-build`). Building with `conda build` is standard conda practice; the repository does not document the exact build command — treat the commands below as the conventional route.
- Network access to `https://github.com/Auto-Mech/MESS.git`.

## Recipe facts (`conda-recipes/mess-static/`)

- `meta.yaml`: `name: mess-static`, `version: 1.1.2`, `git_url: https://github.com/Auto-Mech/MESS.git`, `git_rev: main` (unpinned), `build.number: 0`, `script: bash build.sh`, `license: BSD-3-Clause`.
- `build.sh`: compiles nothing. It requires a `static/` folder in the MESS checkout (exits with `ERROR: expected static/ folder ...` otherwise), copies the executables from `static/` into `$PREFIX/bin`, and `chmod +x` them.
- Recipe test: `test -x "$PREFIX/bin/mess"` (plus a non-fatal `mess -h`).
- The root `conda_build_config.yaml` pins `python: 3.10`.
- The root KiMecO `meta.yaml` lists `mess-static` (unpinned) under `requirements: run` (around line 39).

## Steps

1. Optional but recommended: pin the upstream revision for a reproducible build. Find the commit you want and set `{% set git_rev = "<sha>" %}` in `conda-recipes/mess-static/meta.yaml` instead of `main` (recipe edit → pipeline lane).
2. If the binaries changed, bump `{% set version = ... %}` (or `build.number` for a rebuild of the same version).
3. Build, with outputs kept **outside the repository**:
   ```bash
   conda build conda-recipes/mess-static --output-folder <outside-repo>/conda-bld
   ```
4. Verify in a throwaway env:
   ```bash
   conda create -n mess-test -c <outside-repo>/conda-bld mess-static -y
   conda activate mess-test && which mess && conda deactivate
   ```
   (`conda create --use-local` also works when building into the default `conda-bld` folder.)
5. Upload only with explicit user approval, to a channel the user names:
   ```bash
   anaconda upload <outside-repo>/conda-bld/linux-64/mess-static-<version>-*.tar.bz2
   ```
6. If KiMecO should require the new version, a pin in the root `meta.yaml` (`- mess-static >=<version>`) is a separate pipeline-lane change.

## Key files

- `conda-recipes/mess-static/meta.yaml`, `conda-recipes/mess-static/build.sh`
- `conda_build_config.yaml`, `meta.yaml` (root)
- `LICENSES/MESS_LICENSE`, `wiki/Installation-from-Source.md` (manual binary install alternative)

## Checks & pitfalls

- **License mismatch to raise with the maintainer**: the recipe declares `BSD-3-Clause`, while `LICENSES/MESS_LICENSE` in this repo is the Apache License 2.0. Ask the maintainer which is correct; do not change it on your own.
- `git_rev: main` means two builds of the "same" version can contain different binaries.
- If the upstream repo drops or renames `static/`, `build.sh` fails by design.
- `anaconda upload` is never pre-approved.
- Never build into a path inside the repository (it is not gitignored).

## Lane

Building and testing with outputs outside the repository is operational. Editing the recipe (`git_rev`, version, license) or the root `meta.yaml` pin is pipeline lane.
