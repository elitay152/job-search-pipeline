"""The user's saved employment history, independent of job matching or generated prose."""
from .store import digest


def period(value):
    return str(value) if value is not None else None


def employment_baseline(career):
    jobs = [j.model_dump(mode='json') for j in career.employments]
    # Older imports store employment metadata on evidence rather than separate role records.
    legacy = {}
    for e in career.evidence:
        if not e.eligible or e.kind != 'experience' or e.employment_ids:
            continue
        key = (e.employer, e.official_title, period(e.start), period(e.end))
        if not e.employer and not e.official_title:
            continue
        if any((j['employer'], j['official_title'], j['start'], j['end']) == key for j in jobs):
            continue
        legacy.setdefault(key, dict(id='legacy-' + digest(key)[:16], employer=e.employer,
            official_title=e.official_title, start=period(e.start), end=period(e.end),
            resume_display_title=e.resume_display_title,
            resume_display_title_approved=e.resume_display_title_approved))
    jobs.extend(legacy.values())
    jobs.sort(key=lambda j: (j['start'] or '', j['id']), reverse=True)
    result = {'version': 'employment-baseline-v1', 'jobs': jobs}
    return dict(result, hash=digest(result))


def evidence_roles(evidence, baseline):
    if evidence.employment_ids:
        return tuple(sorted(evidence.employment_ids))
    return tuple(j['id'] for j in baseline['jobs'] if
        (j['employer'], j['official_title'], j['start'], j['end']) ==
        (evidence.employer, evidence.official_title, period(evidence.start), period(evidence.end)))


def ensure_history_bullets(packet, career):
    """Recover omitted job bullets verbatim from inputs, before any review or approval."""
    from .models import Claim
    baseline = employment_baseline(career)
    index = {e.id: e for e in career.evidence}
    covered = set()
    for claim in packet.resume:
        first = index.get(claim.evidence_ids[0]) if claim.evidence_ids else None
        if first and first.kind == 'experience':
            covered.update(i for eid in claim.evidence_ids if eid in index
                           for i in evidence_roles(index[eid], baseline))
    result = packet.model_copy(deep=True)
    used_ids = {c.id for c in result.resume + result.cover_letter}
    for job in baseline['jobs']:
        if job['id'] in covered:
            continue
        candidates = [e for e in career.evidence if e.eligible and e.kind == 'experience'
                      and job['id'] in evidence_roles(e, baseline)]
        if not candidates:
            raise ValueError('Every saved job needs source bullets before generation. Add accomplishments under My experience; no empty job section will be exported.')
        source = candidates[0]
        ident = 'baseline-' + digest([job['id'], source.id])[:20]
        while ident in used_ids:
            ident += '-b'
        used_ids.add(ident)
        result.resume.append(Claim(id=ident, text=source.supported_wording[0], evidence_ids=[source.id]))
        covered.update(evidence_roles(source, baseline))
    return result


def missing_source_jobs(career):
    baseline = employment_baseline(career)
    supported = {ident for e in career.evidence if e.eligible and e.kind == 'experience'
                 for ident in evidence_roles(e, baseline)}
    return [job for job in baseline['jobs'] if job['id'] not in supported]
