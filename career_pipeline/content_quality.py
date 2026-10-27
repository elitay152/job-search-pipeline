"""Explainable presentation heuristics. These do not establish or override factual support."""
import re
from .models import Finding

WORDS = re.compile(r"[\w+#]+", re.UNICODE)
LEDGER = re.compile(r'^\s*(?:database size|active member population|vendor contract|recorded measure|peer training|scope|metric|outcome)\b.*:', re.I)
SCIENTIFIC = re.compile(r'(?<![\w.])\d+(?:\.\d+)?[eE][+-]\d+\b')


def check_content_quality(packet, career, config, plan=None):
    if not config.enabled:
        return []
    findings = []
    index = {e.id:e for e in career.evidence}
    roles = {r.id:r for r in career.employments}
    def warn(code, message, claim=None, section=None, role='voice'):
        findings.append(Finding(role=role, severity='suggestion', code=code, message=message,
            claim_id=claim.id if claim else None, evidence_ids=claim.evidence_ids if claim else [], section=section))
    if plan:
        expected = {}
        for ident in plan.get('skill_evidence', []):
            if ident in index and index[ident].eligible:
                for technology in index[ident].technologies:
                    expected.setdefault(technology.category, []).append(ident)
        shown = {t.category for ident in packet.skills if ident in index and index[ident].eligible
                 for t in index[ident].technologies}
        for category in expected.keys() - shown:
            findings.append(Finding(role='recruiter', severity='suggestion', section='skills',
                evidence_ids=sorted(set(expected[category])), code='missing_skill_category',
                message=f'The selected evidence supports the {category} skills category, but it is absent from Technical Skills. Review whether to include the supported tools.'))
    for claim in packet.resume:
        linked = [index[i] for i in claim.evidence_ids if i in index]
        if not linked or any(e.kind != 'experience' for e in linked):
            continue
        employers = {roles[i].employer for e in linked for i in e.employment_ids if i in roles}
        employers.update(e.employer for e in linked if e.employer)
        if config.check_role_structure and len(employers)>1:
            warn('mixed_employer_scope', 'This passage spans different employers. Clarify placement or split it using the actual evidence; do not guess which role owns it.', claim, 'experience', 'recruiter')
        if len(WORDS.findall(claim.text))<config.minimum_bullet_words:
            warn('fragmented_bullet', 'This experience bullet is very short. Add supported context or combine compatible facts; do not pad it or invent an outcome.', claim, 'experience')
        if LEDGER.search(claim.text):
            warn('ledger_fragment', 'This reads like a source-record label. Compose a complete accomplishment using only supported actions, context and qualifiers.', claim, 'experience')
    for section,claims in [('resume',packet.resume),('cover_letter',packet.cover_letter)]:
        seen=[]
        for claim in claims:
            if config.check_number_display and SCIENTIFIC.search(claim.text):
                warn('scientific_notation', 'Display this quantity in readable decimal or million/billion notation, preserving its exact value, unit and qualifier.', claim,section)
            tokens=WORDS.findall(claim.text.casefold());words=set(tokens)
            for prior,prior_tokens in seen:
                other=set(prior_tokens)
                exact=tokens==prior_tokens
                near=min(len(tokens),len(prior_tokens))>=6 and len(words & other)/max(1,len(words | other))>=config.repetition_similarity
                if exact or near:
                    warn('repeated_passage', f'This passage repeats or closely resembles "{prior.text[:80]}". Remove the repetition or make the distinction clear.',claim,section)
                    break
            seen.append((claim,tokens))
    letter=packet.cover_letter
    if config.check_letter_structure and letter:
        ledger_count=sum(bool(LEDGER.search(c.text)) for c in letter)
        if ledger_count>=2 and ledger_count>=len(letter)/2:
            warn('disconnected_letter', 'The letter is mainly disconnected evidence labels. Write connected paragraphs explaining role relevance and supported examples.',section='cover_letter')
        if len(WORDS.findall(' '.join(c.text for c in letter)))<config.minimum_letter_words:
            warn('thin_letter', 'The letter is shorter than your configured preference. Add supported relevance and examples only where useful.',section='cover_letter')
    return findings
