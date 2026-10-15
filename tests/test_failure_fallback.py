"""Regression tests for the SQL failure-analytics fallback (MongoDB down).

``calculate_sql_failure_summary`` (SQL path) emits a snake_case
``failure_reason`` column, while ``mongo_failure_summary`` (Mongo path) emits
``_id``. The chart rename mappings must accept *both* shapes, otherwise the
Overview raises ``KeyError: "['Failure Reason'] not in index"`` as soon as
MongoDB is unavailable.
"""

import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import app  # noqa: E402

FALLBACK_COLUMNS = [
    "failure_reason",
    "failures",
    "average_delay",
    "maximum_delay",
]

RENAME_BLOCK_RE = re.compile(r'columns=\{[^{}]*"Failure Reason"[^{}]*\}')


def _sample_attempts() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "attempt_status": ["Failed", "Failed", "Delivered"],
            "failure_reason": ["Address missing", None, None],
            "delay_minutes": [12, 30, 0],
        }
    )


def _failure_rename_blocks() -> list[str]:
    source = (REPO / "app.py").read_text(encoding="utf-8")
    return RENAME_BLOCK_RE.findall(source)


# ---------------------------------------------------------------------------
# SQL fallback shape
# ---------------------------------------------------------------------------


def test_sql_fallback_returns_snake_case_columns():
    result = app.calculate_sql_failure_summary(_sample_attempts())

    assert list(result.columns) == FALLBACK_COLUMNS
    # "Address missing" plus the null reason normalised to "Unknown".
    assert len(result) == 2
    assert result["failure_reason"].tolist()[0] == "Address missing"


def test_sql_fallback_empty_shape_is_identical():
    missing_columns = app.calculate_sql_failure_summary(
        pd.DataFrame({"attempt_status": []})
    )
    no_failures = app.calculate_sql_failure_summary(
        pd.DataFrame(
            {
                "attempt_status": ["Delivered"],
                "failure_reason": [None],
                "delay_minutes": [0],
            }
        )
    )

    assert list(missing_columns.columns) == FALLBACK_COLUMNS
    assert list(no_failures.columns) == FALLBACK_COLUMNS
    assert missing_columns.empty and no_failures.empty


# ---------------------------------------------------------------------------
# Rename mappings must accept the SQL fallback shape
# ---------------------------------------------------------------------------


def test_every_failure_rename_maps_failure_reason():
    blocks = _failure_rename_blocks()

    # Overview + Failure Analysis both build the same chart source frame.
    assert len(blocks) >= 2, "expected Overview and Failure Analysis renames"

    for block in blocks:
        assert '"failure_reason": "Failure Reason"' in block, (
            "rename block does not map the SQL fallback column:\n" + block
        )


def test_overview_chart_renders_from_sql_fallback():
    """Reproduce the Overview's exact frame + index selection, offline."""

    result = app.calculate_sql_failure_summary(_sample_attempts())
    source = (REPO / "app.py").read_text(encoding="utf-8")
    block = RENAME_BLOCK_RE.search(source).group(0)

    mapping = dict(re.findall(r'"(\w+)":\s*"([^"]+)"', block))
    display = result.rename(columns=mapping)

    # This is the selection that used to raise KeyError before the fix.
    chart = display[["Failure Reason", "Failures"]].set_index("Failure Reason")

    assert not chart.empty
    assert list(chart.columns) == ["Failures"]


def test_mongo_shape_still_supported_by_the_same_mapping():
    """The Mongo path emits `_id`; the mapping must keep honouring it."""

    mongo_frame = pd.DataFrame(
        {"_id": ["Address missing"], "failure_count": [7]}
    )
    source = (REPO / "app.py").read_text(encoding="utf-8")
    block = RENAME_BLOCK_RE.search(source).group(0)
    mapping = dict(re.findall(r'"(\w+)":\s*"([^"]+)"', block))

    display = mongo_frame.rename(columns=mapping)

    assert "Failure Reason" in display.columns
