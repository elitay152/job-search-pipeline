"""Characters that XML 1.0 cannot represent in editable application documents."""
import re

XML_INVALID = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]')
# Generated evidence IDs (fact-…, resume-…) are audit metadata and must never appear in prose.
REFERENCE_CODE = re.compile(r'\b(?:fact|resume|answer|context|baseline|ev)-[0-9a-f]{6,}\b')


def reference_codes(text, known_ids=()):
    found = set(REFERENCE_CODE.findall(text))
    found.update(ident for ident in known_ids if len(ident) >= 6 and ident in text)
    return sorted(found)


def strip_reference_codes(text, known_ids=()):
    """Last-resort cleanup for rendering; the review gate still reports the original text."""
    for code in reference_codes(text, known_ids):
        text = text.replace(code, '')
    text = re.sub(r'\s*\((?:\s*[,;]\s*)*\s*\)', '', text)  # Parentheses left holding only separators.
    text = re.sub(r'\s+([.,;:])', r'\1', text)
    return re.sub(r' {2,}', ' ', text).strip()
