#!/usr/bin/env python3
"""Run doc-extract.py against all test documents and output -robot.txt files.

Usage:
    python tests/run_doc_extract.py

For each file in tests/test-docs/, this script:
  1. Runs doc-extract.py on it (with a 300s timeout)
  2. Writes the extracted text to tests/test-docs/{filename}-robot.txt
  3. Prints a summary of results
"""
import subprocess
import sys
import os
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "doc-extract.py"
TEST_DIR = REPO_ROOT / "tests" / "test-docs"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python3"

SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".docx", ".txt"}


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


def extract_text(file_path: Path) -> tuple[str, str | None]:
    """Run doc-extract.py and return (text, error_message)."""
    if not SCRIPT.exists():
        return "", f"doc-extract.py not found at {SCRIPT}"

    # Pass the Anthropic API key from the .env file so vision OCR works
    env = os.environ.copy()
    api_key = os.environ.get("ANTHROPIC_VISION_API_KEY") or _load_env_key()
    if api_key:
        env["ANTHROPIC_VISION_API_KEY"] = api_key

    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(SCRIPT), str(file_path)],
            capture_output=True, text=True, timeout=300,
            env=env
        )
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT (300s)"
    except Exception as e:
        return "", str(e)

    if result.returncode != 0:
        return "", f"Exit code {result.returncode}: {result.stderr[:300]}"

    output = result.stdout
    if "--- EXTRACTED TEXT ---" in output:
        text = output.split("--- EXTRACTED TEXT ---", 1)[1].strip()
    else:
        text = output.strip()

    return text, None


def format_result(file_name: str, status: str, char_count: int, excerpt: str) -> str:
    """Format a single document result line."""
    icon = "✅" if status == "OK" else "❌"
    excerpt_display = excerpt[:120].replace("\n", " | ") if excerpt else ""
    return f"{icon} {status:<8} {char_count:>6} chars  {file_name}  {excerpt_display}"


def main():
    # Find test documents
    files = []
    for f in sorted(TEST_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS and "-robot.txt" not in f.name:
            files.append(f)

    if not files:
        print(f"No supported test documents found in {TEST_DIR}")
        print(f"Supported extensions: {SUPPORTED_EXTS}")
        sys.exit(1)

    print(f"Found {len(files)} test document(s) in {TEST_DIR}")
    print(f"Using: {SCRIPT}")
    print(f"{'='*80}")
    print()

    results = []

    for file_path in files:
        print(f"Processing: {file_path.name}...", end=" ", flush=True)

        text, error = extract_text(file_path)

        if error:
            print("❌")
            results.append(format_result(file_path.name, "FAIL", 0, error))
            # Write error as robot text
            robot_path = file_path.parent / f"{file_path.name}-robot.txt"
            robot_path.write_text(f"ERROR: {error}\n")
            continue

        # Write robot.txt
        robot_path = file_path.parent / f"{file_path.name}-robot.txt"
        robot_path.write_text(text)

        char_count = len(text)
        if char_count < 20:
            status = "SHORT"
        else:
            status = "OK"
        print(f"✅ ({char_count} chars)")

        excerpt = text[:120].replace("\n", " | ")
        results.append(format_result(file_path.name, status, char_count, excerpt))

    # Summary
    print()
    print(f"{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    for r in results:
        print(r)

    # Stats
    total = len(results)
    ok = sum(1 for r in results if "OK" in r and "SHORT" not in r)
    short = sum(1 for r in results if "SHORT" in r)
    failed = sum(1 for r in results if "FAIL" in r)
    print()
    print(f"Total: {total}  OK: {ok}  Short (<20 chars): {short}  Failed: {failed}")


if __name__ == "__main__":
    main()
