"""Deterministic factual gate and document-level review, independent of any UI."""
import re
from .models import Career, Packet, Finding
from .text_safety import XML_INVALID


def group_key(e):
    return ('roles:' + '|'.join(sorted(e.employment_ids)) if e.employment_ids else
            f'{e.employer}|{e.official_title}|{e.start}|{e.end}')


def document_plan(career, selected):
    eligible = [e for e in career.evidence if e.eligible and e.id in selected]
    groups = {}
    for e in eligible:
        if e.kind == 'experience':
            # References may span two roles. Keep that scope, rather than duplicating claims.
            key = group_key(e)
            groups.setdefault(key, []).append(e.id)
    return {
        'experience_groups': [{'key': key, 'evidence_ids': ids,
            'minimum_bullets': min(len(ids), career.presentation.minimum_recent_bullets)} for key, ids in groups.items()],
        'publications': [e.id for e in eligible if e.kind == 'publication'] if career.presentation.include_publications else [],
        'education': [e.id for e in eligible if e.kind == 'education'] if career.presentation.include_education else [],
        'skill_evidence': [e.id for e in eligible if e.technologies] if career.presentation.include_skills else [],
        'instructions': 'Skills stay in one categorized section. Include selected publications and education. '
                        'Preserve contextual labels for portfolio, academic and training tools.'}


def audit(packet, career, grounded_claims=None, include_cover_letter=True):
    """Fail closed on wording, references, uncertainty and extra skills.

    Exact confirmed factual statements are supported source text, not a claim that a user
    approved the generated packet. Unreviewed paraphrases still fail this conservative gate.
    """
    grounded_claims = grounded_claims or set()
    index = {e.id: e for e in career.evidence}
    findings = []
    for claim in packet.resume + packet.cover_letter:
        if XML_INVALID.search(claim.text):
            findings.append(Finding(role='evidence', claim_id=claim.id, evidence_ids=claim.evidence_ids,
                severity='error', code='invalid_document_character',
                message='Passage contains a control character that Word cannot store. Rewrite it from the cited evidence using ordinary text; preserve the facts.'))
        linked = [index[i] for i in claim.evidence_ids if i in index]
        valid = len(linked) == len(claim.evidence_ids) and all(
            e.eligible and claim.text in e.supported_wording for e in linked)
        if not valid and claim.id not in grounded_claims:
            findings.append(Finding(role='evidence', claim_id=claim.id, evidence_ids=claim.evidence_ids,
                severity='error', code='unsupported_wording', message='Claim is not exact supported wording from every linked, confirmed record.'))
    # The renderer assigns a passage to its first evidence record's section.
    rendered_groups = {group_key(index[c.evidence_ids[0]]) for c in packet.resume
                       if c.evidence_ids and c.evidence_ids[0] in index
                       and index[c.evidence_ids[0]].kind == 'experience'}
    eligible_groups = {}
    for e in career.evidence:
        if e.eligible and e.kind == 'experience':
            eligible_groups.setdefault(group_key(e), []).append(e.id)
    for group, ids in eligible_groups.items():
        if group not in rendered_groups:
            findings.append(Finding(role='recruiter', severity='error', section='experience',
                evidence_ids=ids, code='missing_employment_history',
                message='A confirmed employment scope has no rendered resume passage. Include supported work history from these sources; do not invent new experience.'))
    for ident in packet.skills:
        e = index.get(ident)
        if not e or not e.eligible or not e.technologies:
            findings.append(Finding(role='evidence', evidence_ids=[ident], section='skills',
                severity='error', code='unsupported_skill', message='Skill source is missing, uncertain or has no supported technology.'))
    if packet.cover_letter and not include_cover_letter:
        findings.append(Finding(role='evidence', severity='error', section='cover_letter', code='unrequested_document', message='Cover letter was not requested; return an empty cover_letter array.'))
    if not packet.resume or (include_cover_letter and not packet.cover_letter):
        findings.append(Finding(role='evidence', severity='error', section='packet', code='empty_packet', message='Each requested document requires factual content.'))
    ids = [c.id for c in packet.resume + packet.cover_letter]
    if len(ids) != len(set(ids)):
        findings.append(Finding(role='evidence', severity='error', section='packet', code='duplicate_claim_id', message='Claim IDs must be unique.'))
    return findings


def reviews(packet, requirements, career, plan=None, grounded_claims=None):
    findings = audit(packet, career, grounded_claims, include_cover_letter=(plan or {}).get('include_cover_letter', True))
    claims = packet.resume + packet.cover_letter
    used = {i for c in claims for i in c.evidence_ids} | set(packet.skills)
    for q in requirements:
        if q.classification in ('unsupported', 'needs_clarification'):
            findings.append(Finding(role='recruiter', requirement_id=q.id, severity='gap',
                code='experience_gap', message=f'{q.classification}: {q.text}'))
        elif not used.intersection(q.evidence_ids):
            findings.append(Finding(role='recruiter', requirement_id=q.id, severity='suggestion',
                code='missing_coverage', section='experience', message='Presentation: relevant evidence is missing from the packet.'))
    if plan:
        for pending in plan.get('pending_sources', []):
            findings.append(Finding(role='evidence', section=pending['kind'], evidence_ids=[pending['id']],
                severity='gap', code='source_confirmation_needed', message='Source-backed record needs factual confirmation before it can be generated.'))
        resume_used = {i for c in packet.resume for i in c.evidence_ids}
        for kind in ('publications', 'education'):
            for ident in plan[kind]:
                if ident not in resume_used:
                    findings.append(Finding(role='recruiter', section=kind, evidence_ids=[ident],
                        severity='suggestion', code='missing_section_content', message=f'Include selected {kind} evidence.'))
        for group in plan['experience_groups']:
            passages = [c for c in packet.resume if set(c.evidence_ids).intersection(group['evidence_ids'])]
            if len(passages) < group['minimum_bullets']:
                findings.append(Finding(role='recruiter', section='experience', evidence_ids=group['evidence_ids'],
                    severity='suggestion', code='thin_role', message=f"Role has {len(passages)} bullets; {group['minimum_bullets']} supported bullets are available and requested."))
        if plan['skill_evidence'] and not set(packet.skills).intersection(plan['skill_evidence']):
            findings.append(Finding(role='recruiter', section='skills', evidence_ids=plan['skill_evidence'],
                severity='suggestion', code='missing_skills', message='Add one categorized Technical Skills section using evidence-backed tools and context labels.'))
    seen = set()
    for c in packet.resume:
        if c.text in seen or re.search(r'\b(rockstar|ninja|world-class|passionate|synergy)\b', c.text, re.I):
            findings.append(Finding(role='voice', claim_id=c.id, severity='suggestion', code='voice', message='Review repetition or inflated language.'))
        seen.add(c.text)
    return findings
