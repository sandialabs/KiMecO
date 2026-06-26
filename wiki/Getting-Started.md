# Getting started

## 1) Create the initial JSON input

You have two options:

- Recommended: use the GUI utility `kmo_start`.
  - Run `kmo_start`.
  - Fill the tabs in order.
  - Save/write the generated JSON file.
- Manual: build the JSON yourself.
  - Read the sections below in this manual.
  - Create a JSON file containing the mandatory keys first.
  - Add optional keys to specify your run conditions.

## 2) Utilities overview

- `kmo_start`: input builder GUI. Use this first if you are new to KiMecO.
- `kmo input.json`: main optimization run command. It reads your input JSON and launches KiMecO.
- `kmoui input.json`: analysis/inspection GUI for completed runs.
- `kmopp input.json`: postprocessing command-line utility.
