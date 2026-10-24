"""Local, persistent evidence updates and readable job-fit summaries for any frontend."""
import uuid
from collections import Counter
from pathlib import Path
from .models import Career, Evidence
from .store import digest, now


def save_profile(career, path='local/career.json'):
    career = Career.model_validate(career.model_dump(mode='json'))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(career.model_dump_json(indent=2), encoding='utf-8')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def add_gap_answer(career, requirement, answer, *, role_ids=(), tool='', usage='', context='professional',
                   ownership='contributed', confirmed=False, jd_hash='', path='local/career.json'):
    if not confirmed:
        raise ValueError('Confirm the factual answer before adding it to your evidence library.')
    if not answer.strip():
        raise ValueError('Describe what you personally did before saving.')
    if requirement.kind == 'constraint':
        raise ValueError('Practical preferences are separate from career evidence.')
    if tool.strip() and not usage.strip():
        raise ValueError('Describe how you used the tool.')
    ident = 'answer-' + digest([jd_hash, requirement.text])[:20]
    evidence = Evidence(id=ident, project=requirement.text[:150], employment_ids=list(role_ids),
        kind='experience' if role_ids else 'skill' if tool else 'project',
        actions=[answer.strip()], ownership=ownership,
        technologies=[{'name': tool.strip(), 'usage': usage.strip(), 'context': context}] if tool.strip() else [],
        sources=[{'reference': 'User-confirmed follow-up ' + now(), 'status': 'user_confirmed', 'excerpt': answer.strip()}],
        confirmed_statements=[answer.strip()],
        fact_details={'requirement_excerpt': requirement.excerpt, 'job_hash': jd_hash})
    updated = career.model_dump(mode='json')
    updated['evidence'] = [e for e in updated['evidence'] if e['id'] != ident] + [evidence.model_dump(mode='json')]
    result = Career.model_validate(updated)
    save_profile(result, path)
    return result


def analyze_job(jd, career):
    from .pipeline import extract, map_requirements
    return map_requirements(extract(jd), career)


def fit_report(requirements, packet=None):
    """Evidence coverage, not an ATS score or a prediction of hiring outcomes."""
    used = {i for claim in packet.resume + packet.cover_letter for i in claim.evidence_ids} | set(packet.skills) if packet else set()
    supported = [q for q in requirements if q.kind == 'skill' and q.classification in ('direct', 'transferable')]
    covered = [q for q in supported if used.intersection(q.evidence_ids)] if packet else []
    counts = Counter(q.classification for q in requirements if q.kind == 'skill')
    return {'direct': counts['direct'], 'transferable': counts['transferable'],
        'gaps': counts['unsupported'], 'clarifications': counts['needs_clarification'],
        'supported': len(supported), 'covered': len(covered),
        'required_supported': sum(q.priority == 'required' for q in supported),
        'required_total': sum(q.kind == 'skill' and q.priority == 'required' for q in requirements),
        'practical_constraints': sum(q.kind == 'constraint' for q in requirements)}
