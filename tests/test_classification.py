"""Tests for document classification logic.

All documents now go through Claude Haiku (classify_by_llm), not rules.
"""
from unittest.mock import patch
from bot import classify, classify_by_llm


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


class TestClassifyDirectToLLM:
    """classify() goes directly to LLM for every document."""

    def test_classify_calls_llm_for_obvious_text(self):
        """Even clear text like 'Fatou Manneh CPR card' goes to LLM, not rules."""
        employees = make_employees(["Fatou Manneh"])
        with patch("bot.classify_by_llm", return_value=("Fatou Manneh", "04 - CPR & First Aid")) as mock_llm:
            emp, cat, method = classify("Fatou Manneh CPR card", "", CAT_KEYWORDS, employees)
            mock_llm.assert_called_once()
            assert emp == "Fatou Manneh"
            assert cat == "04 - CPR & First Aid"
            assert method == "llm"

    def test_classify_calls_llm_for_ambiguous_text(self):
        """Ambiguous text also goes to LLM."""
        employees = make_employees(["Fatou Manneh"])
        with patch("bot.classify_by_llm", return_value=("Fatou Manneh", "03 - Health Screening")) as mock_llm:
            emp, cat, method = classify("TB test results for Fatou Manneh", "", CAT_KEYWORDS, employees)
            mock_llm.assert_called_once()
            assert emp == "Fatou Manneh"
            assert method == "llm"

    def test_classify_llm_fails_falls_to_manual(self):
        """When LLM fails, classify returns None, None, 'failed'."""
        employees = make_employees(["Fatou Manneh"])
        with patch("bot.classify_by_llm", return_value=(None, None)):
            emp, cat, method = classify("unrecognizable text", "", CAT_KEYWORDS, employees)
            assert emp is None
            assert cat is None
            assert method == "failed"
