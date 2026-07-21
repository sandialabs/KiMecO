# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3] - 2026-07-21

### Fixed
- Two-sided derivatives properly skipped for frozen parameters in the linear sensitivity analysis.

## [1.0.2] - 2026-07-20

### Added
- Frozen parameters can now be specified in the input JSON file using the `fixed_params` key. This allows users to exclude certain parameters from being perturbed during optimization.
- Working example for ethyl oxidation with frozen parameters included in the `example` folder.

## [1.0.1] - 2026-07-14

### Added
- Visualization and export of KMO databases in the database tab of the GUI.
- Improved score printing for clearer run output.

### Fixed
- Minor print formatting issue.

### Changed
- Unified the package version across `pyproject.toml`, `setup.py`, and `meta.yaml`.

## [1.0.0] - 2024

### Added
- Initial public release of KiMecO (Kinetic Mechanism Optimizer).

[1.0.3]: https://github.com/sandialabs/KiMecO/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/sandialabs/KiMecO/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/sandialabs/KiMecO/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/sandialabs/KiMecO/releases/tag/v1.0.0
