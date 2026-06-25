#!/usr/bin/env python3
"""Run classification against all test-doc extracted texts.

For each test document, reads the -robot.txt extracted text, runs
the classification algorithm (both rules and LLM), and writes a
.json result file alongside the original document.

Usage:
    python tests/classify_test_docs.py

Output:
    tests/test-docs/{original_name}.json — classification result
    Console summary of all results.
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
TEST_DIR = REPO_ROOT / "tests" / "test-docs"
BOT_PATH = REPO_ROOT / "bot.py"

# Supported document extensions
SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".docx", ".txt"}

# Comprehensive employee roster based on test documents and known AFH employees
# This covers all names that appear in the test documents
EMPLOYEE_ROSTER = {
    "fatou manneh": {"name": "Fatou Manneh"},
    "nicholas kachu khamali": {"name": "Nicholas Kachu Khamali"},
    "philomena joseph renaux": {"name": "Philomena Joseph Renaux"},
    "philomena renaux": {"name": "Philomena Renaux"},
}

# Category keywords matching the config.json schema
CAT_KEYWORDS = {
    "01 - Identity & Employment": [
        "id", "driver", "license", "passport", "i-9", "w-4", "ssn",
        "application", "picture", "photo", "work permit", "identification",
    ],
    "02 - Background Check": [
        "background", "dshs", "fingerprint", "authorization", "disclosure",
    ],
    "03 - Health Screening": [
        "tb", "tuberculosis", "ppd", "chest", "x-ray", "quantiferon",
        "covid", "vaccination", "n95", "fit test",
    ],
    "04 - CPR & First Aid": [
        "cpr", "bls", "first aid", "aed", "american heart", "red cross",
        "resuscitation", "basic life support",
    ],
    "05 - Orientation & Training": [
        "orientation", "basic training", "75 hour", "70 hour", "food handler",
        "food safety", "hiv", "bloodborne", "food worker card",
    ],
    "06 - HCA Certification & CE": [
        "hca", "cna", "license", "certification", "continuing education",
        "ceu", "dementia", "mental health", "specialty", "ddst",
        "nursing assistant",
    ],
    "07 - Nurse Delegation": [
        "delegation", "nurse deleg",
    ],
    "08 - Administrator Training": [
        "administrator", "admin training",
    ],
}


def load_robot_text(filepath: Path) -> str | None:
    """Read the -robot.txt file for a given document."""
    robot_path = filepath.parent / f"{filepath.name}-robot.txt"
    if robot_path.exists():
        return robot_path.read_text().strip()
    return None


def classify_file(filepath: Path) -> dict:
    """Run classification on a single test document and return results."""
    # Read extracted text
    text = load_robot_text(filepath)
    if text is None:
        return {"status": "ERROR", "error": "No robot.txt found — run tests/run_doc_extract.py first"}

    filename = filepath.name

    # Build employee dict in the format bot.classify_by_rules expects
    employees = {}
    for key, info in EMPLOYEE_ROSTER.items():
        employees[key] = {"id": f"folder_{key.replace(' ', '_')}", "name": info["name"]}

    # Import bot module and run classification
    sys.path.insert(0, str(REPO_ROOT))
    import bot as bot_mod

    # Run LLM classification (all documents go through the LLM now)
    api_key = os.environ.get("ANTHROPIC_VISION_API_KEY") or _load_env_key()
    emp, cat = None, None
    llm_used = False
    if api_key:
        old_key = os.environ.get("ANTHROPIC_VISION_API_KEY")
        os.environ["ANTHROPIC_VISION_API_KEY"] = api_key
        import importlib
        importlib.reload(bot_mod)
        try:
            emp, cat = bot_mod.classify_by_llm(text, filename, employees, CAT_KEYWORDS)
            llm_used = True
        except Exception as e:
            pass
        finally:
            if old_key:
                os.environ["ANTHROPIC_VISION_API_KEY"] = old_key

    # Determine overall result
    text_preview = text[:200] + "..." if len(text) > 200 else text

    result = {
        "source_file": filepath.name,
        "text_length": len(text),
        "text_preview": text_preview,
        "llm": {
            "used": llm_used,
            "employee": emp,
            "category": cat,
        },
    }

    return result


def _load_env_key() -> str | None:
    """Read ANTHROPIC_VISION_API_KEY from the project .env file."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("ANTHROPIC_VISION_API_KEY="):
            return line.split("=", 1)[1]
    return None


def format_result(doc_name: str, result: dict) -> str:
    """Format a result line for console output."""
    llm = result.get("llm", {})
    emp = llm.get("employee") or "—"
    cat = llm.get("category") or "—"

    icon = "✅" if emp != "—" and cat != "—" else "❌" if emp == "—" and cat == "—" else "⚠️"
    chars = result.get("text_length", 0)
    return f"{icon} {emp:<25} {cat:<35} {chars:>5}ch  {doc_name}"


def main():
    # Collect test documents (exclude existing robot.txt and json files)
    files = []
    for f in sorted(TEST_DIR.iterdir()):
        if (f.is_file()
                and f.suffix.lower() in SUPPORTED_EXTS
                and "-robot.txt" not in f.name
                and f.suffix.lower() != ".json"):
            files.append(f)

    if not files:
        print(f"No test documents found in {TEST_DIR}")
        sys.exit(1)

    print(f"Classifying {len(files)} document(s) in {TEST_DIR}")
    print(f"{'='*110}")
    print(f"{'EMP':<25} {'CATEGORY':<35} {'SIZE':<6}  FILE")
    print(f"{'-'*110}")

    results = []

    for filepath in files:
        result = classify_file(filepath)
        results.append((filepath, result))

        # Write JSON result alongside the original file
        json_path = filepath.parent / f"{filepath.name}.json"
        json_path.write_text(json.dumps(result, indent=2, default=str))
        print(format_result(filepath.name, result))

    # Summary
    print(f"{'='*110}")
    total = len(results)
    full_match = sum(1 for _, r in results
                     if r["llm"]["employee"] and r["llm"]["category"])
    partial = sum(1 for _, r in results
                  if (r["llm"]["employee"] or r["llm"]["category"])
                  and not (r["llm"]["employee"] and r["llm"]["category"]))
    no_match = sum(1 for _, r in results
                   if not r["llm"]["employee"] and not r["llm"]["category"])
    print(f"\nTotal: {total}  Full match: {full_match}  Partial: {partial}  No match: {no_match}")


if __name__ == "__main__":
    main()
