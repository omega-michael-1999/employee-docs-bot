"""Tests for ambiguity-aware three-tier classification."""
from bot import classify_by_rules, WAC_CATEGORIES


def make_employees(names):
    return {n.lower(): {"id": f"folder_{n.lower().replace(' ', '_')}", "name": n} for n in names}


CAT_KEYWORDS = {
    "01 - Identity & Employment": ["id", "driver", "license", "passport", "i-9", "w-4", "ssn", "application", "picture", "photo", "work permit"],
    "02 - Background Check": ["background", "dshs", "fingerprint", "authorization", "disclosure"],
    "03 - Health Screening": ["tb", "tuberculosis", "ppd", "chest", "x-ray", "quantiferon", "covid", "vaccination", "n95", "fit test"],
    "04 - CPR & First Aid": ["cpr", "bls", "first aid", "aed", "american heart", "red cross", "resuscitation"],
    "05 - Orientation & Training": ["orientation", "basic training", "75 hour", "70 hour", "food handler", "food safety", "hiv", "bloodborne"],
    "06 - HCA Certification & CE": ["hca", "cna", "license", "certification", "continuing education", "ceu", "dementia", "mental health", "specialty", "ddst"],
    "07 - Nurse Delegation": ["delegation", "nurse deleg"],
    "08 - Administrator Training": ["administrator", "admin training"],
}


# --- Confidence scoring tests ---

def test_full_name_high_confidence():
    """Multi-word full name match returns high confidence."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, conf = classify_by_rules("Fatou Manneh TB test results", "", CAT_KEYWORDS, employees)
    assert emp == "Fatou Manneh"
    assert cat == "03 - Health Screening"
    assert conf == "high"


def test_single_word_name_low_confidence():
    """Single-word name match (shouldn't happen with valid rosters, but edge case)."""
    employees = make_employees(["Sandra"])
    emp, cat, conf = classify_by_rules("Sandra CPR card", "", CAT_KEYWORDS, employees)
    assert emp == "Sandra"
    assert conf == "low", "Single-word name should be low confidence"


def test_unique_keyword_high_confidence():
    """Keyword unique to one category returns high confidence."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, conf = classify_by_rules("Fatou Manneh CPR recertification", "", CAT_KEYWORDS, employees)
    assert emp == "Fatou Manneh"
    assert cat == "04 - CPR & First Aid"
    assert conf == "high", "CPR is unique to category 04"


def test_shared_keyword_low_confidence():
    """Keyword shared across multiple categories returns low confidence."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, conf = classify_by_rules("Fatou Manneh license renewal", "", CAT_KEYWORDS, employees)
    assert emp == "Fatou Manneh"
    # "license" appears in both "01 - Identity & Employment" and "06 - HCA Certification & CE"
    # The function should still return a category (first match wins), but with low confidence
    assert conf == "low", "'license' appears in multiple categories, should be low confidence"


def test_high_confidence_skips_llm():
    """High confidence result is suitable for immediate return without LLM."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, conf = classify_by_rules("Fatou Manneh CPR card", "", CAT_KEYWORDS, employees)
    assert conf == "high"
    assert emp is not None
    assert cat is not None


def test_no_match_returns_none():
    """No match at all returns None, None, None."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, conf = classify_by_rules("unrelated document text", "", CAT_KEYWORDS, employees)
    assert emp is None
    assert cat is None
    assert conf is None
