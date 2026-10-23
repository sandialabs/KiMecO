---
name: pint-unit-string-comparison
description: "pint pitfall: comparing a pint Unit with a string, or testing `str in ureg.get_compatible_units(...)`, matches only canonical unit names, not aliases such as 's', 'min', 'us'. Read before validating user-given unit strings."
type: project
verified: 2026-10-22 against working tree
---
- `Unit.__eq__(str)` ends in `UnitsContainer.__eq__`, which parses the string **without** the unit
  registry: `Unit('second') == 's'` is False. So `x in ureg.get_compatible_units('[time]')`
  accepts `'second'` but rejects `'s'`, `'min'`, `'us'`.
- `TimeProfile.plot` validated `x_unit` this way until 2026-10-22; it now uses
  `TimeProfile._unit_to_seconds`, which converts through pint (`Q_(1.0, unit).to('s')`, so every
  time unit and alias such as `s`, `min`, `us`), treats `ms`/`millisecond` case-insensitively, and
  raises ValueError for unknown or non-time units.
- `gui/input_sections/experiments_section.py` builds its pressure-unit list with
  `str(unit) for unit in ureg.get_compatible_units(...)`: that list holds canonical names only.

**Why:** a unit check written this way silently rejects the short aliases users type.
**How to apply:** validate a unit string by converting it (`ureg.parse_units`, or the class's
own converter such as `_unit_to_seconds`), never by membership in `get_compatible_units`.

Sources: pint `pint/facets/plain/unit.py::Unit.__eq__`, `pint/util.py::UnitsContainer.__eq__`
(the version installed with Cantera's units registry); `kimeco/experiments/t_profile.py::TimeProfile`.
