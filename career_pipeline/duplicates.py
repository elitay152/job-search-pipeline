"""Find education and publication records saved more than once in different formats.

Re-importing a resume adds records such as "Master of Science in Data Analytics | Western
Governors University | June 2023" next to an earlier confirmed "... | 2023-06". Experience
records are left alone: overlapping bullets at different detail levels are intentional.
"""
import re

GENERIC_INSTITUTION_WORDS = {'university', 'college', 'of', 'the', 'school', 'institute', 'at', 'and'}


def _normal(text):
    text = re.sub(r'^\s*[-•*]\s*', '', text).casefold()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def _first_text(e):
    return (e.supported_wording or [e.project])[0]


def duplicate_key(e):
    text = _first_text(e)
    if e.kind == 'publication':
        title = re.search(r'\(\d{4}[a-z]?\)\.?\s*(.+?)[.?!](?:\s|$)', re.sub(r'^\s*[-•*]\s*', '', text))
        return ('publication', _normal(title.group(1) if title else text))
    if e.kind == 'education':
        degree = re.sub(r'\b(student|candidate)\b', '', _normal(text.split('|')[0]))
        return ('education', ' '.join(degree.split()))
    return None


def _institution(e):
    parts = _first_text(e).split('|')
    return set(_normal(parts[1]).split()) - GENERIC_INSTITUTION_WORDS if len(parts) > 1 else set()


def _preference(e):
    # Keep what the user explicitly confirmed, then the record without a stray list marker.
    confirmed = any(source.status == 'user_confirmed' for source in e.sources)
    return (not confirmed, bool(re.match(r'^\s*[-•*]', _first_text(e))))


def duplicate_groups(career):
    """Lists of duplicate records, each ordered with the record to keep first."""
    by_key = {}
    for e in career.evidence:
        key = duplicate_key(e)
        if key and key[1]:
            by_key.setdefault(key, []).append(e)
    groups = []
    for records in by_key.values():
        while records:
            first, rest = records[0], records[1:]
            # The same degree at a different institution is a separate record.
            same = [first] + [e for e in rest if first.kind != 'education' or not _institution(first)
                              or not _institution(e) or _institution(first) & _institution(e)]
            records = [e for e in records if e not in same]
            if len(same) > 1:
                groups.append(sorted(same, key=_preference))
    return groups


def hidden_duplicates(career):
    return {e.id for group in duplicate_groups(career) for e in group[1:]}


def merge_duplicates(career):
    """Remove duplicate records, keeping each removed record's sources on the one that stays."""
    data = career.model_dump(mode='json')
    records = {e['id']: e for e in data['evidence']}
    merged = []
    for group in duplicate_groups(career):
        kept = records[group[0].id]
        references = {s['reference'] for s in kept['sources']}
        for duplicate in group[1:]:
            for source in records[duplicate.id]['sources']:
                if source['reference'] not in references:
                    kept['sources'].append(source)
                    references.add(source['reference'])
        merged.append({'kept': group[0].id, 'removed': [e.id for e in group[1:]], 'text': _first_text(group[0])})
    removed = {ident for item in merged for ident in item['removed']}
    data['evidence'] = [e for e in data['evidence'] if e['id'] not in removed]
    return type(career).model_validate(data), merged
