"""Tests for document classification logic."""
from bot import classify_by_rules, classify, WAC_CATEGORIES


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


# --- Word-boundary tests for employee name matching ---

def test_exact_name_match():
    """Full name in text should match."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, _ = classify_by_rules("CPR card for Fatou Manneh", "", CAT_KEYWORDS, employees)
    assert emp == "Fatou Manneh"


def test_name_in_filename():
    """Name in filename should match."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, _ = classify_by_rules("", "Fatou Manneh - CPR.pdf", CAT_KEYWORDS, employees)
    assert emp == "Fatou Manneh"


def test_partial_name_does_not_match():
    """First-name-only should not match a multi-word name."""
    employees = make_employees(["Josephine Smith"])
    emp, cat, _ = classify_by_rules("Joe is the cert holder", "", CAT_KEYWORDS, employees)
    assert emp is None, "Short name should not match longer name"


def test_compound_surname_match():
    """Full compound surname with hyphen should match."""
    employees = make_employees(["Anna Smith-Jones"])
    emp, cat, _ = classify_by_rules("Anna Smith-Jones TB test", "", CAT_KEYWORDS, employees)
    assert emp == "Anna Smith-Jones"


def test_compound_surname_no_partial():
    """Just 'Smith' should not match 'Smith-Jones'."""
    employees = make_employees(["Anna Smith-Jones"])
    emp, cat, _ = classify_by_rules("Smith certificate", "", CAT_KEYWORDS, employees)
    assert emp is None, "Surname fragment should not match compound surname"


def test_unrecognized_name_returns_none():
    """Name not in roster returns None."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, _ = classify_by_rules("John Doe CPR card", "", CAT_KEYWORDS, employees)
    assert emp is None


def test_empty_text_returns_no_match():
    """Empty text and filename should return no match."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, _ = classify_by_rules("", "", CAT_KEYWORDS, employees)
    assert emp is None
    assert cat is None


def test_case_insensitive_name_match():
    """Name matching should be case-insensitive."""
    employees = make_employees(["Fatou Manneh"])
    emp, cat, _ = classify_by_rules("fatou manneh cpr card", "", CAT_KEYWORDS, employees)
    assert emp == "Fatou Manneh"


def test_name_with_comma_in_roster():
    """Roster names with trailing ', CNA' should match on the name part."""
    employees = make_employees(["Themobile Malinki, CNA"])
    emp, cat, _ = classify_by_rules("Themobile Malinki TB test", "", CAT_KEYWORDS, employees)
    assert emp == "Themobile Malinki, CNA"


def test_employee_with_initials():
    """Initials in text should not match full name."""
    employees = make_employees(["Jonathan Kasiibante"])
    emp, cat, _ = classify_by_rules("J. Kasiibante", "", CAT_KEYWORDS, employees)
    assert emp is None, "Initials should not match full name"


# --- Word-boundary tests for category keyword matching ---

def test_keyword_in_text_matches():
    """Known keyword in text should match the right category."""
    employees = make_employees(["Test Employee"])
    emp, cat, _ = classify_by_rules("CPR certification card", "", CAT_KEYWORDS, employees)
    assert cat == "04 - CPR & First Aid"


def test_keyword_in_larger_word_does_not_match():
    """Keyword that appears inside a longer word should not match."""
    employees = make_employees(["Test Employee"])
    emp, cat, _ = classify_by_rules("unlicensed caregiver note", "", CAT_KEYWORDS, employees)
    assert cat is None, "'license' inside 'unlicensed' should not match"


def test_multiple_keyword_hits():
    """Document with multiple keywords should still match a category."""
    employees = make_employees(["Test Employee"])
    emp, cat, _ = classify_by_rules("CPR and First Aid certificate", "", CAT_KEYWORDS, employees)
    assert cat == "04 - CPR & First Aid"


def test_keyword_match_from_filename():
    """Keyword in filename should match category."""
    employees = make_employees(["Test Employee"])
    emp, cat, _ = classify_by_rules("", "background_check.pdf", CAT_KEYWORDS, employees)
    assert cat == "02 - Background Check"
