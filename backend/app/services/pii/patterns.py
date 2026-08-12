"""Structured-PII regex patterns shared by the regex detector.

These are deliberately conservative, language-agnostic patterns for structured
identifiers (email, URL, phone, long numeric IDs). Names, addresses, and other
free-text PII in non-English scripts require the multilingual detector.
"""

import re

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
URL_RE = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.IGNORECASE)
# Long digit runs and common ID-like tokens (case numbers, MRNs, etc.).
ID_RE = re.compile(r"\b(?:ID|MRN|SSN|NINO|CASE)[-:#\s]?\d{4,}\b|\b\d{6,}\b", re.IGNORECASE)

# Priority order: earlier categories win when spans overlap.
ORDERED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", EMAIL_RE),
    ("url", URL_RE),
    ("phone", PHONE_RE),
    ("id", ID_RE),
]
