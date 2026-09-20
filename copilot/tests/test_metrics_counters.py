"""The counters the health dashboard reads.

Removals are rare in a healthy system, so the counting path is easy to ship broken and
never notice. These pin the two things that would break it silently: the classifier
mapping, and the counter key the dashboard looks for.
"""

import pytest

from copilot.schemas import RemovedClaim
from copilot.verify import removal_reason_code


@pytest.mark.parametrize("reason, expected", [
    ("no source cited", "no_citation"),
    ("cites records that are not in this patient's chart: lab:6101", "wrong_patient"),
    ("cites records no tool returned in this turn (restated without a lookup): lab:6001",
     "restated_without_lookup"),
    ("phrases a clinical recommendation or diagnosis (product boundary)", "recommendation"),
    ("value(s) not found in the cited records: 5.4", "unsupported_value"),
    ("empty claim", "empty_claim"),
    ("off-topic question: chart facts discarded", "off_topic"),
])
def test_every_removal_reason_has_a_code(reason, expected):
    assert removal_reason_code(reason) == expected


def test_an_unrecognised_reason_is_counted_rather_than_dropped():
    """A reworded reason must land in 'other', never vanish."""
    assert removal_reason_code("some reason nobody has written yet") == "other"
    assert removal_reason_code("") == "other"


def test_every_reason_check_claim_can_return_is_classified():
    """Guards against a new removal reason being added without a code.

    Reads the reasons out of the verifier's source, so adding one there and forgetting the
    classifier fails here rather than showing up as 'other' on the dashboard months later.
    """
    import inspect
    import re

    from copilot import verify

    source = inspect.getsource(verify.check_claim)
    literals = re.findall(r'return f?"([^"{]+)', source)
    reasons = [text for text in literals if text.strip()]
    assert len(reasons) >= 6, "expected check_claim to return several distinct reasons"

    unclassified = [r for r in reasons if removal_reason_code(r) == "other"]
    assert unclassified == [], f"removal reasons with no code: {unclassified}"


def test_counter_key_matches_what_the_dashboard_reads():
    """app.py writes `removed_<code>`; metrics.php reads 'removed_' . $code. Keep them equal."""
    claim = RemovedClaim(text="Potassium 9.9", reason="value(s) not found in the cited records: 9.9")
    key = f"removed_{removal_reason_code(claim.reason)}"
    assert key == "removed_unsupported_value"
