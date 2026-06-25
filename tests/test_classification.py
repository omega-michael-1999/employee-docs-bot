"""Tests for document classification logic.

All documents now go through Claude Haiku (classify_by_llm), not rules.
"""
from unittest.mock import patch
from bot import classify, classify_by_llm, _fuzzy_match_employee


def make_employees(names):
    """Build the employee dict format used by the bot."""
    return {n.lower(): {"id": f"folder_{n.lower().replace(' ', '_')}", "name": n} for n in names}


CAT_KEYWORDS = {
    "01 - Identity & Employment": ["id", "driver", "license", "passport", "i-9", "w-4", "ssn", "application"],
    "02 - Background Check": ["background", "dshs", "fingerprint"],
    "03 - Health Screening": ["tb", "tuberculosis", "ppd", "chest", "x-ray", "quantiferon", "covid", "vaccination"],
    "04 - CPR & First Aid": ["cpr", "bls", "first aid", "aed", "american heart", "red cross"],
    "05 - Orientation & Training": ["orientation", "basic training", "75 hour", "70 hour", "food handler", "hiv"],
    "06 - HCA Certification & CE": ["hca", "cna", "license", "certification", "continuing education", "ceu"],
    "07 - Nurse Delegation": ["delegation", "nurse deleg"],
    "08 - Administrator Training": ["administrator", "admin training"],
}


class TestFuzzyNameMatching:
    """Fuzzy matching catches names with extra/missing middle names."""

    def test_exact_match(self):
        """Exact name match still works."""
        employees = make_employees(["Fatou Manneh"])
        result = _fuzzy_match_employee("Fatou Manneh", employees)
        assert result == "Fatou Manneh"

    def test_extra_middle_name_found(self):
        """'Jayden Kambi Omondi' matches roster entry 'Jayden Omondi'."""
        employees = make_employees(["Jayden Omondi"])
        result = _fuzzy_match_employee("Jayden Kambi Omondi", employees)
        assert result == "Jayden Omondi"

    def test_middle_name_variation(self):
        """'Philomena Joseph Renaux' matches roster entry 'Philomena Renaux'."""
        employees = make_employees(["Philomena Renaux"])
        result = _fuzzy_match_employee("Philomena Joseph Renaux", employees)
        assert result == "Philomena Renaux"

    def test_unknown_name_returns_none(self):
        """Completely different name returns None."""
        employees = make_employees(["Fatou Manneh"])
        result = _fuzzy_match_employee("John Smith", employees)
        assert result is None

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        employees = make_employees(["jayden omondi"])
        result = _fuzzy_match_employee("Jayden Kambi Omondi", employees)
        assert result == "jayden omondi"


class TestUnknownEmployeeNameProposed:
    """When the LLM finds a name not in the roster, it's still proposed."""

    def test_classify_unknown_name_proposed_to_user(self):
        """classify() returns the name even when not in roster -- caller decides what to do."""
        employees = make_employees(["Fatou Manneh"])
        with patch("bot.classify_by_llm", return_value=("Jayden Kambi Omondi", "02 - Background Check", "DSHS auth")):
            emp, cat, desc, method = classify("DSHS form for Jayden Kambi Omondi", "", CAT_KEYWORDS, employees)
            # The name is passed through, even though not in roster
            assert emp == "Jayden Kambi Omondi"
            assert method == "llm"


class TestClassifyDirectToLLM:
    """classify() goes directly to LLM for every document."""

    def test_classify_calls_llm_for_obvious_text(self):
        """Even clear text like 'Fatou Manneh CPR card' goes to LLM, not rules."""
        employees = make_employees(["Fatou Manneh"])
        with patch("bot.classify_by_llm", return_value=("Fatou Manneh", "04 - CPR & First Aid", "CPR card")) as mock_llm:
            emp, cat, desc, method = classify("Fatou Manneh CPR card", "", CAT_KEYWORDS, employees)
            mock_llm.assert_called_once()
            assert emp == "Fatou Manneh"
            assert cat == "04 - CPR & First Aid"
            assert method == "llm"

    def test_classify_calls_llm_for_ambiguous_text(self):
        """Ambiguous text also goes to LLM."""
        employees = make_employees(["Fatou Manneh"])
        with patch("bot.classify_by_llm", return_value=("Fatou Manneh", "03 - Health Screening", "TB test results")) as mock_llm:
            emp, cat, desc, method = classify("TB test results for Fatou Manneh", "", CAT_KEYWORDS, employees)
            mock_llm.assert_called_once()
            assert emp == "Fatou Manneh"
            assert method == "llm"

    def test_classify_llm_fails_falls_to_manual(self):
        """When LLM fails, classify returns None, None, 'failed'."""
        employees = make_employees(["Fatou Manneh"])
        with patch("bot.classify_by_llm", return_value=(None, None, None)):
            emp, cat, desc, method = classify("unrecognizable text", "", CAT_KEYWORDS, employees)
            assert emp is None
            assert cat is None
            assert method == "failed"
