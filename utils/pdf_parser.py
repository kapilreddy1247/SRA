"""
utils/pdf_parser.py — Smart Resume Analyzer
=============================================
Extracts clean text from a resume PDF using PyPDF2.
Handles common edge cases: multi-column layouts, garbled encoding,
empty pages, scanned-only PDFs, and unicode noise.

Usage:
    from utils.pdf_parser import extract
    text = extract("/path/to/resume.pdf")
    # returns plain string, empty string on failure
"""

import re
import os

# ── PyPDF2 import with friendly error ────────────────────────────────────────
try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError:
    try:
        from PyPDF2 import PdfReader
        from PyPDF2.errors import PdfReadError
    except ImportError:
        raise ImportError(
            "pypdf is not installed.\n"
            "Run: pip install pypdf"
        )


# ── Public API ────────────────────────────────────────────────────────────────

def extract(pdf_path: str) -> str:
    """
    Extract and clean text from a PDF resume.

    Args:
        pdf_path: Absolute or relative path to the PDF file.

    Returns:
        Cleaned plain-text string.
        Returns empty string if the file cannot be read or has no text.
    """
    if not os.path.exists(pdf_path):
        return ""

    try:
        reader = PdfReader(pdf_path, strict=False)
    except (PdfReadError, Exception):
        return ""

    pages_text = []
    for page in reader.pages:
        try:
            raw = page.extract_text() or ""
            if raw.strip():
                pages_text.append(raw)
        except Exception:
            continue  # skip unreadable pages silently

    if not pages_text:
        return ""

    combined = "\n".join(pages_text)
    return _clean(combined)


# ── Internal cleaning pipeline ────────────────────────────────────────────────

def _clean(text: str) -> str:
    """
    Apply a chain of cleaning steps to raw PDF text.
    Order matters — each step builds on the previous.
    """
    text = _fix_encoding(text)
    text = _remove_noise(text)
    text = _normalise_whitespace(text)
    text = _fix_broken_words(text)
    return text.strip()


def _fix_encoding(text: str) -> str:
    """
    Replace common Unicode/encoding artefacts that appear in PDF extraction:
      ligatures, non-breaking spaces, smart quotes, etc.
    """
    replacements = {
        "\ufb01": "fi",   # ﬁ ligature
        "\ufb02": "fl",   # ﬂ ligature
        "\ufb00": "ff",   # ﬀ ligature
        "\ufb03": "ffi",  # ﬃ ligature
        "\ufb04": "ffl",  # ﬄ ligature
        "\u00e2\u0080\u0099": "'",  # garbled apostrophe
        "\u2019": "'",    # right single quotation mark
        "\u2018": "'",    # left single quotation mark
        "\u201c": '"',    # left double quotation mark
        "\u201d": '"',    # right double quotation mark
        "\u2013": "-",    # en dash
        "\u2014": "-",    # em dash
        "\u00a0": " ",    # non-breaking space
        "\u200b": "",     # zero-width space
        "\u200c": "",     # zero-width non-joiner
        "\u200d": "",     # zero-width joiner
        "\t": " ",        # tabs → spaces
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    # Encode to ASCII ignoring truly unreadable chars, then back to str
    # Preserve C++ and C# before ASCII stripping
    text = text.replace("C++", "CPlusPlus").replace("C#", "CSharp")
    text = text.encode("ascii", errors="ignore").decode("ascii")
    # Restore after stripping
    text = text.replace("CPlusPlus", "C++").replace("CSharp", "C#")
    return text


def _remove_noise(text: str) -> str:
    """
    Remove elements that add noise for skill extraction:
      - Email addresses
      - URLs / LinkedIn profiles
      - Phone numbers
      - Page numbers / headers like "Page 1 of 2"
      - Long runs of special characters (borders, dividers)
      - Standalone single characters on a line
    """
    # URLs
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"www\.\S+", " ", text)
    text = re.sub(r"linkedin\.com/\S*", " ", text)
    text = re.sub(r"github\.com/\S*", " ", text)

    # Emails
    text = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", " ", text)

    # Phone numbers (various formats)
    text = re.sub(r"[\+\(]?\d[\d\s\-\(\)]{7,}\d", " ", text)

    # Page numbers
    text = re.sub(r"\bpage\s+\d+\s+of\s+\d+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+\s*/\s*\d+\b", " ", text)

    # Lines that are just decorative (----, ====, ....., •••)
    text = re.sub(r"^[\s\-=_\.•|~*#]{3,}$", " ", text, flags=re.MULTILINE)

    # Standalone bullet/symbol characters
    text = re.sub(r"[•◦▪▸►●○◆◇➤➢✓✔✗✘]", " ", text)

    # Dates (to reduce noise — not needed for skill extraction)
    text = re.sub(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
                  r"\s*\.?\s*\d{0,4}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{4}\s*[-–]\s*(?:\d{4}|Present|Current)\b",
                  " ", text, flags=re.IGNORECASE)

    # Percentage and numeric-only tokens (scores like "8.5/10", "95%")
    text = re.sub(r"\b\d+[\./]\d+\b", " ", text)
    text = re.sub(r"\b\d+%\b", " ", text)

    return text


def _normalise_whitespace(text: str) -> str:
    """
    Collapse multiple spaces/newlines into single spaces.
    Preserve line breaks between sections (double newlines → single).
    """
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces to single
    text = re.sub(r" {2,}", " ", text)
    # Remove spaces at start/end of each line
    lines = [line.strip() for line in text.splitlines()]
    # Remove completely empty lines in runs of 2+
    cleaned_lines = []
    prev_empty    = False
    for line in lines:
        if line == "":
            if not prev_empty:
                cleaned_lines.append(line)
            prev_empty = True
        else:
            cleaned_lines.append(line)
            prev_empty = False
    return "\n".join(cleaned_lines)


def _fix_broken_words(text: str) -> str:
    """
    Rejoin words that were split across lines by PDF extraction,
    e.g. 'Ma-\nchine Learning' → 'Machine Learning'.
    Also fix 'C + +' → 'C++', 'Java Script' → 'JavaScript'.
    """
    # Hyphenated line breaks
    text = re.sub(r"-\n([a-z])", r"\1", text)

    # Mid-word line breaks (lowercase continues on next line)
    # e.g. "Post\ngreSQL" → "PostgreSQL"
    text = re.sub(r"([a-zA-Z])\n([a-z])", r"\1\2", text)

    # Common tech skill spacing issues
    tech_fixes = {
        r"\bJava\s+Script\b"    : "JavaScript",
        r"\bType\s+Script\b"    : "TypeScript",
        r"\bC\s*\+\s*\+\b"      : "C++",
        r"\bC\s*#\b"            : "C#",
        r"\bNode\s*\.\s*js\b"   : "Node.js",
        r"\bVue\s*\.\s*js\b"    : "Vue.js",
        r"\bReact\s*\.\s*js\b"  : "React.js",
        r"\bNext\s*\.\s*js\b"   : "Next.js",
        r"\bExpress\s*\.\s*js\b": "Express.js",
        r"\bPower\s+BI\b"       : "Power BI",
        r"\bMachine\s+Learning\b": "Machine Learning",
        r"\bDeep\s+Learning\b"  : "Deep Learning",
        r"\bNatural\s+Language\s+Processing\b": "NLP",
        r"\bArtificial\s+Intelligence\b": "AI",
        r"\bData\s+Science\b"   : "Data Science",
        r"\bFull\s+Stack\b"     : "Full Stack",
        r"\bGit\s+Hub\b"        : "GitHub",
        r"\bLinked\s+In\b"      : "LinkedIn",
    }
    for pattern, replacement in tech_fixes.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return text


# ── Skill matcher helper ──────────────────────────────────────────────────────

def find_skills_in_text(text: str, skill_names: list) -> list:
    """
    Find which skill names from the master list appear in extracted text.
    Returns list of (skill_name, confidence) tuples.

    confidence = 1.0 if exact match, 0.8 if case-insensitive match.

    Args:
        text        : cleaned resume text from extract()
        skill_names : list of skill name strings from skills table

    Usage:
        skills_table = db.execute("SELECT name FROM skills").fetchall()
        skill_names  = [r["name"] for r in skills_table]
        matched      = find_skills_in_text(resume_text, skill_names)
    """
    text_lower = text.lower()
    matched    = []

    for skill in skill_names:
        # Build word-boundary pattern to avoid partial matches
        # e.g. "R" should not match inside "React" or "Keras"
        escaped = re.escape(skill)

        # For very short skills (1-2 chars like R, C), use strict boundaries
        if len(skill) <= 2:
            pattern = r"(?<![A-Za-z])" + escaped + r"(?![A-Za-z+#])"
        else:
            pattern = r"\b" + escaped + r"\b"

        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                # Exact case match → higher confidence
                if re.search(pattern, text):
                    matched.append((skill, 1.0))
                else:
                    matched.append((skill, 0.85))
        except re.error:
            # Fallback for skills with special regex chars
            if skill.lower() in text_lower:
                matched.append((skill, 0.8))

    return matched


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pdf_parser.py <resume.pdf>")
        sys.exit(1)

    path = sys.argv[1]
    text = extract(path)

    if not text:
        print("No text extracted — PDF may be scanned/image-only.")
        sys.exit(1)

    print(f"Extracted {len(text)} characters, {len(text.split())} words\n")
    print("─" * 60)
    print(text[:2000])
    if len(text) > 2000:
        print(f"\n... ({len(text) - 2000} more characters)")