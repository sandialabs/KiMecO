from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from kimeco.scoring_f.scoring import Scoring


def _mdl(
    theory: float,
    experiment: float,
    total: float,
    scores: dict[str, float],
) -> Any:
    return cast(Any, SimpleNamespace(
        theory_score=theory,
        experiment_score=experiment,
        score=total,
        sop=SimpleNamespace(scores=scores),
    ))


def _exp(name: str, weight: float = 1.0) -> Any:
    return cast(Any, SimpleNamespace(name=name, weight=weight))


def _scoring(experiments: list[Any]) -> Scoring:
    return Scoring(
        settings={"experiments": experiments},
        initial_SOP=cast(Any, None),
    )


def _value_lines(block: str) -> list[str]:
    """Return the numeric value lines (those right after a header line)."""
    lines = block.split("\n")
    value_lines: list[str] = []
    for idx, line in enumerate(lines):
        if line.strip().startswith("THEORY"):
            value_lines.append(lines[idx + 1])
    return value_lines


def _header_lines(block: str) -> list[str]:
    """Return the header lines that begin a sub-block (start with THEORY)."""
    return [
        ln for ln in block.split("\n") if ln.strip().startswith("THEORY")
    ]


def test_block_starts_with_empty_line_then_label() -> None:
    sf = _scoring([_exp("exp_0")])
    block = sf.format_score_breakdown(
        [_mdl(1.0, 2.0, 5.0, {"exp_0": 4.0})], "GOAT"
    )
    lines = block.split("\n")
    assert lines[0] == ""
    assert lines[1] == "[GOAT (species weighting only)]"


def test_final_line_is_weighted_average_score() -> None:
    sf = _scoring([_exp("exp_0", weight=1.0), _exp("exp_1", weight=3.0)])
    models = [
        _mdl(1.0, 2.0, 4.0, {"exp_0": 4.0, "exp_1": 8.0}),
        _mdl(3.0, 4.0, 6.0, {"exp_0": 2.0, "exp_1": 6.0}),
    ]
    block = sf.format_score_breakdown(models, "GOAT")
    last = block.strip().split("\n")[-1]
    assert last.startswith("WEIGHTED AVERAGE SCORE:")
    # Average of the two total scores (4.0, 6.0) -> 5.0
    assert "5.000" in last


def test_species_weighted_values_are_correct() -> None:
    sf = _scoring([_exp("exp_0", weight=1.0), _exp("exp_1", weight=3.0)])
    # Single model keeps the averages trivial to verify.
    block = sf.format_score_breakdown(
        [_mdl(1.0, 2.0, 5.0, {"exp_0": 4.0, "exp_1": 8.0})], "GOAT"
    )
    value_lines = _value_lines(block)
    assert len(value_lines) == 1  # only the species-weighted block

    values = [float(v) for v in value_lines[0].split()]
    # Columns: THEORY, EXP, exp_0, exp_1 (experiment weights are not applied)
    assert values == [1.0, 2.0, 4.0, 8.0]


def test_averaging_over_multiple_models() -> None:
    sf = _scoring([_exp("exp_0", weight=1.0)])
    models = [
        _mdl(1.0, 2.0, 3.0, {"exp_0": 4.0}),
        _mdl(3.0, 4.0, 5.0, {"exp_0": 6.0}),
    ]
    block = sf.format_score_breakdown(models, "GENERATION")
    unweighted = [float(v) for v in _value_lines(block)[0].split()]
    # THEORY avg = 2.0, EXP avg = 3.0, exp_0 avg = 5.0
    assert unweighted == [2.0, 3.0, 5.0]


def test_columns_wrap_at_seven_per_line() -> None:
    experiments = [_exp(f"exp_{i}") for i in range(7)]  # 7 + THEORY + EXP = 9
    sf = _scoring(experiments)
    scores = {f"exp_{i}": float(i) for i in range(7)}
    block = sf.format_score_breakdown(
        [_mdl(1.0, 2.0, 3.0, scores)], "GOAT"
    )
    header_lines = _header_lines(block)
    # The single block wraps 9 cols into a 7-column line and a 2-column line,
    # so exactly one header line begins with THEORY.
    assert len(header_lines) == 1
    # No value line should hold more than 7 numbers.
    for vline in _value_lines(block):
        assert len(vline.split()) <= 7
    # First wrapped line must carry exactly 7 columns.
    assert len(_value_lines(block)[0].split()) == 7


def test_empty_models_reports_no_scored_models() -> None:
    sf = _scoring([_exp("exp_0")])
    block = sf.format_score_breakdown([], "GOAT")
    assert block == (
        "\n[GOAT (species weighting only)]\nNo scored models to report."
    )


def test_non_finite_scored_models_are_filtered_out() -> None:
    sf = _scoring([_exp("exp_0")])
    models = [
        _mdl(1.0, 2.0, float("inf"), {"exp_0": 4.0}),
        _mdl(3.0, 4.0, 5.0, {"exp_0": 6.0}),
    ]
    block = sf.format_score_breakdown(models, "GOAT")
    unweighted = [float(v) for v in _value_lines(block)[0].split()]
    # Only the finite-score model contributes.
    assert unweighted == [3.0, 4.0, 6.0]


def test_all_non_finite_reports_no_scored_models() -> None:
    sf = _scoring([_exp("exp_0")])
    models = [
        _mdl(1.0, 2.0, float("inf"), {"exp_0": 4.0}),
        _mdl(3.0, 4.0, float("nan"), {"exp_0": 6.0}),
    ]
    block = sf.format_score_breakdown(models, "NM SWARM")
    assert block == (
        "\n[NM SWARM (species weighting only)]\n"
        "No scored models to report."
    )


def test_none_entries_are_ignored() -> None:
    sf = _scoring([_exp("exp_0")])
    models = [None, _mdl(1.0, 2.0, 3.0, {"exp_0": 4.0})]
    block = sf.format_score_breakdown(cast(Any, models), "GOAT")
    unweighted = [float(v) for v in _value_lines(block)[0].split()]
    assert unweighted == [1.0, 2.0, 4.0]


def test_no_experiments_only_theory_and_exp_columns() -> None:
    sf = _scoring([])
    block = sf.format_score_breakdown(
        [_mdl(1.0, 2.0, 3.0, {})], "GOAT"
    )
    header_lines = _header_lines(block)
    assert len(header_lines) == 1
    for header in header_lines:
        assert header.split() == ["THEORY", "EXP"]
    assert _value_lines(block)[0].split() == ["1.000", "2.000"]


def test_missing_experiment_key_does_not_crash() -> None:
    sf = _scoring([_exp("exp_0"), _exp("exp_1")])
    # Model is missing the "exp_1" score.
    block = sf.format_score_breakdown(
        [_mdl(1.0, 2.0, 3.0, {"exp_0": 4.0})], "GOAT"
    )
    value_line = _value_lines(block)[0]
    assert "nan" in value_line
    # exp_0 still reported correctly.
    assert "4.000" in value_line


def test_long_experiment_name_expands_column_width() -> None:
    long_name = "very_long_experiment_name"
    sf = _scoring([_exp(long_name)])
    block = sf.format_score_breakdown(
        [_mdl(1.0, 2.0, 3.0, {long_name: 7.0})], "GOAT"
    )
    header = _header_lines(block)[0]
    assert long_name in header


def test_large_values_use_scientific_notation() -> None:
    sf = _scoring([_exp("exp_0", weight=1.0)])
    # Total score >= 1000 -> scientific notation in the final line too.
    block = sf.format_score_breakdown(
        [_mdl(1234.5, 2.0, 5678.0, {"exp_0": 4.0})], "GOAT"
    )
    unweighted = _value_lines(block)[0].split()
    # THEORY column is >= 1000 -> scientific notation with 2 decimals.
    assert unweighted[0] == "1.23E+03"
    # Values below 1000 keep 3-decimal fixed notation.
    assert unweighted[1] == "2.000"
    last = block.strip().split("\n")[-1]
    assert last == "WEIGHTED AVERAGE SCORE: 5.68E+03"


def test_all_columns_in_a_block_are_uniformly_aligned() -> None:
    # Enough experiments to force wrapping, with mixed magnitudes and name
    # lengths so a wide uniform column width is required.
    experiments = [_exp(f"exp_{i}") for i in range(8)]
    sf = _scoring(experiments)
    scores = {f"exp_{i}": float(i) for i in range(8)}
    scores["exp_3"] = 12345.0  # forces scientific notation width
    block = sf.format_score_breakdown(
        [_mdl(1.0, 2.0, 3.0, scores)], "GOAT"
    )
    lines = block.split("\n")

    def is_value_line(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        try:
            float(stripped.split()[0])
            return True
        except ValueError:
            return False

    value_line_indices = [
        idx for idx, line in enumerate(lines) if is_value_line(line)
    ]
    # 8 experiments + THEORY + EXP = 10 columns -> the single block wraps
    # into a 7-column row and a 3-column row -> 2 value lines total.
    assert len(value_line_indices) == 2

    for idx in value_line_indices:
        header = lines[idx - 1]
        value = lines[idx]
        # Uniform width + single-space separators mean the value line and its
        # header line have identical length, so the columns line up exactly.
        assert len(header) == len(value)

    # Derive the uniform column width from the 7-column row and confirm the
    # 3-column continuation row is consistent with it, i.e. its columns start
    # at the same offsets.
    full_row = next(
        lines[i] for i in value_line_indices if len(lines[i].split()) == 7
    )
    partial_row = next(
        lines[i] for i in value_line_indices if len(lines[i].split()) == 3
    )
    width = (len(full_row) - 6) // 7  # 7 cols + 6 single-space separators
    assert len(full_row) == 7 * width + 6
    assert len(partial_row) == 3 * width + 2


def _header_length(block: str) -> int:
    return len(_header_lines(block)[0])


def test_explicit_width_forces_shared_column_spacing() -> None:
    sf = _scoring([_exp("exp_0")])
    # A block whose natural width would be small (values ~1 digit).
    narrow = sf.format_score_breakdown(
        [_mdl(1.0, 2.0, 3.0, {"exp_0": 4.0})], "GOAT - AVERAGE"
    )
    # A reference block with a large THEORY column -> wider natural width.
    wide = sf.format_score_breakdown(
        [_mdl(9999.0, 2.0, 3.0, {"exp_0": 4.0})], "GENERATION - AVERAGE"
    )
    ref_width = sf.breakdown_width(
        [_mdl(9999.0, 2.0, 3.0, {"exp_0": 4.0})]
    )
    assert ref_width is not None
    # Without sharing, the two blocks have different header lengths.
    assert _header_length(narrow) != _header_length(wide)
    # Sharing the reference width makes the narrow block match the wide one.
    shared = sf.format_score_breakdown(
        [_mdl(1.0, 2.0, 3.0, {"exp_0": 4.0})],
        "GOAT - AVERAGE",
        width=ref_width,
    )
    assert _header_length(shared) == _header_length(wide)


def test_shared_width_never_shrinks_below_natural_width() -> None:
    sf = _scoring([_exp("exp_0")])
    # Passing a tiny width must not clip a wide value; the block keeps its
    # own natural width instead.
    block = sf.format_score_breakdown(
        [_mdl(9999.0, 2.0, 3.0, {"exp_0": 4.0})],
        "GOAT - AVERAGE",
        width=1,
    )
    natural = sf.format_score_breakdown(
        [_mdl(9999.0, 2.0, 3.0, {"exp_0": 4.0})], "GOAT - AVERAGE"
    )
    assert _header_length(block) == _header_length(natural)
