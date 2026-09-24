from pcs7_analyzer.checks import CHECKS, get_check
from pcs7_analyzer.model import Severity


def test_check_ids_unique_and_complete():
    ids = [c.id for c in CHECKS]
    assert len(ids) == len(set(ids))
    for c in CHECKS:
        assert c.title and c.manual_ref and isinstance(c.severity, Severity)


def test_consistency_is_separate_check():
    assert get_check("CONS_ES_SERVER").severity is Severity.HIGH
    assert get_check("HW_RELEASED")
