import json
import re
import time
import uuid
from pathlib import Path
from typing import Protocol
from .models import Career, Requirement, Packet, Finding, Settings
from .providers import Gateway, PROMPT_VERSION
from .store import Store, digest, now

TOKENS = re.compile(r'[a-z0-9+#]+')
STOP = {'the','a','an','and','of','to','in','with','for','is','you','we','required','preferred','must','have','experience','using'}

def words(text):
    return set(TOKENS.findall(text.lower())) - STOP

def extract(jd):
    if not 20 <= len(jd.strip()) <= 50000:
        raise ValueError('Job description must contain 20–50,000 characters')
    requirements = []
    priority = 'ambiguous'
    for line in re.split(r'[\n;]+', jd):
        line = line.strip(' •-\t')
        if not line:
            continue
        low = line.lower()
        if re.search(r'\b(required|requirements|must)\b', low):
            priority = 'required'
        elif re.search(r'\b(preferred|nice to have|bonus)\b', low):
            priority = 'preferred'
        if len(words(line)) < 1:
            continue
        requirements.append(Requirement(id=f'q{len(requirements)+1}', text=line, excerpt=line,
            priority=priority, kind='constraint' if re.search(r'\b(remote|hybrid|onsite|salary|travel|authorization|location)\b', low) else 'skill'))
    return requirements

class Retriever(Protocol):
    def retrieve(self, requirement: Requirement, career: Career) -> list[tuple]: ...

class LexicalRetriever:
    """Transparent tag overlap followed by lexical overlap; no embeddings."""
    def retrieve(self, requirement, career):
        query = words(requirement.text)
        ranked = []
        for e in career.evidence:
            tags = words(' '.join(e.tags + [t.name for t in e.technologies]))
            approved = words(' '.join(e.approved_wording))
            score = 3*len(query & tags) + len(query & approved)
            if score:
                ranked.append((e, score, query <= (tags | approved)))
        return sorted(ranked, key=lambda item: (-item[1], item[0].id))[:3]

def map_requirements(requirements, career, retriever=None):
    retriever = retriever or LexicalRetriever()
    for q in requirements:
        if q.kind == 'constraint':
            q.classification = 'needs_clarification'
            continue
        matches = retriever.retrieve(q, career)
        eligible = [m for m in matches if m[0].eligible]
        q.evidence_ids = [m[0].id for m in eligible]
        if eligible:
            q.classification = 'direct' if any(m[2] for m in eligible) else 'transferable'
        elif matches:
            q.classification = 'needs_clarification'
    return requirements

def audit(packet, career):
    """Fail closed: IDs are necessary; exact approved wording is also required.

    This deliberately rejects new paraphrases rather than claiming semantic entailment.
    """
    index = {e.id: e for e in career.evidence}
    findings = []
    for claim in packet.resume + packet.cover_letter:
        linked = [index[i] for i in claim.evidence_ids if i in index]
        valid = (len(linked) == len(claim.evidence_ids) and all(e.eligible for e in linked)
                 and any(claim.text in e.approved_wording for e in linked)
                 and all(claim.text in e.approved_wording for e in linked))
        if not valid:
            findings.append(Finding(role='evidence', claim_id=claim.id, evidence_ids=claim.evidence_ids,
                severity='error', message='Claim is not exact approved wording supported by every linked, confirmed record.'))
    if not packet.resume or not packet.cover_letter:
        findings.append(Finding(role='evidence', severity='error', message='Resume and letter require factual content.'))
    ids = [c.id for c in packet.resume + packet.cover_letter]
    if len(ids) != len(set(ids)):
        findings.append(Finding(role='evidence', severity='error', message='Claim IDs must be unique.'))
    return findings

def reviews(packet, requirements, career):
    findings = audit(packet, career)
    claims = packet.resume + packet.cover_letter
    used = {i for c in claims for i in c.evidence_ids}
    for q in requirements:
        if q.classification in ('unsupported', 'needs_clarification'):
            findings.append(Finding(role='recruiter', requirement_id=q.id, severity='gap',
                message=f'{q.classification}: {q.text}'))
        elif not used.intersection(q.evidence_ids):
            findings.append(Finding(role='recruiter', requirement_id=q.id, severity='suggestion',
                message='Presentation: relevant evidence is missing from the packet.'))
    seen = set()
    for c in packet.resume:  # Reusing a fact in the letter is expected.
        if c.text in seen or re.search(r'\b(rockstar|ninja|world-class|passionate|synergy)\b', c.text, re.I):
            findings.append(Finding(role='voice', claim_id=c.id, severity='suggestion', message='Review repetition or inflated language.'))
        seen.add(c.text)
    return findings

def load_style(path):
    root = Path(path)
    # Explicitly load the portable skill. Raw examples are never interpolated into instructions.
    skill = (root/'SKILL.md').read_text()
    profile = json.loads((root/'profile.json').read_text())
    if not profile.get('approved'):
        raise ValueError('Writing profile must be approved or use the labeled neutral default')
    guidance_file = root/'resume_guidance.md'
    guidance = guidance_file.read_text() if guidance_file.exists() else ''
    bundle = {'skill': skill, 'profile': profile, 'resume_guidance': guidance}
    return {'version': profile['version'], 'hash': digest(bundle),
            'guidance_version': 'resume-guidance-v1' if guidance else None,
            'instructions': skill + '\n' + guidance + '\n' + json.dumps(profile)}

def run(jd, career, store=None, settings=None, style_path='writing_style', strategy='C'):
    store = store or Store()
    settings = settings or Settings()
    style = load_style(style_path)
    run_id = str(uuid.uuid4())
    started = time.monotonic()
    manifest = {'id': run_id, 'created': now(), 'updated': now(), 'status': 'running',
        'input_hash': digest(jd), 'evidence_hash': digest(career.model_dump(mode='json')),
        'prompt_version': PROMPT_VERSION, 'schema_version': '2', 'style': style,
        'settings': settings.model_dump(), 'strategy': strategy, 'stages': [], 'versions': [],
        'revision_count': 0, 'artifacts': [], 'approved': False}
    store.save(manifest)
    gateway = Gateway(store, settings)
    def stage(name, function):
        ts = time.monotonic()
        try:
            result = function()
            manifest['stages'].append({'name': name, 'status': 'passed', 'latency': time.monotonic()-ts})
            return result
        except Exception:
            manifest['stages'].append({'name': name, 'status': 'failed', 'latency': time.monotonic()-ts})
            raise
    try:
        requirements = stage('extract', lambda: extract(jd))
        requirements = stage('retrieve', lambda: map_requirements(requirements, career))
        selected = {i for q in requirements for i in q.evidence_ids}
        evidence = [e.model_dump(mode='json') for e in career.evidence if e.eligible and (strategy == 'A' or e.id in selected)]
        manifest['requirements'] = [q.model_dump() for q in requirements]
        manifest['discovery_questions'] = discovery_questions(requirements)
        manifest['selected_evidence'] = [e['id'] for e in evidence]
        # Persist private snapshots locally, never log document contents to stdout.
        store.event(run_id, 'inputs', {'jd': jd, 'career': career.model_dump(mode='json')})
        payload = {'job_description': jd, 'requirements': manifest['requirements'], 'evidence': evidence,
                   'style': style['instructions']}
        packet = stage('generate', lambda: Packet.model_validate(gateway.call('generate', payload)))
        seen = set()
        for revision in range(settings.max_revisions + 1):
            signature = digest(packet.model_dump())
            findings = stage('validate', lambda: reviews(packet, requirements, career))
            if strategy == 'C':
                review = stage('review', lambda: gateway.call('review', dict(payload, packet=packet.model_dump())))
                known_claims = {c.id for c in packet.resume + packet.cover_letter}
                known_requirements = {q.id for q in requirements}
                for raw in review.get('findings', []):
                    f = Finding.model_validate(raw)
                    if f.role == 'evidence' or f.severity == 'error':
                        raise ValueError('Model reviewer may not substitute for deterministic auditor')
                    if f.role == 'recruiter' and (f.claim_id not in known_claims or f.requirement_id not in known_requirements):
                        continue
                    if f.role == 'voice' and f.claim_id not in known_claims:
                        continue
                    findings.append(f)
            version = {'number': revision, 'packet': packet.model_dump(), 'findings': [f.model_dump() for f in findings],
                       'hash': signature, 'created': now()}
            manifest['versions'].append(version)
            store.event(run_id, 'version', version)
            manifest['revision_count'] = revision
            store.save(manifest)
            actionable = [f for f in findings if f.severity in ('error', 'suggestion')]
            if strategy != 'C' or not actionable:
                manifest['stopping_reason'] = 'one_shot' if strategy != 'C' else 'material_issues_resolved'
                break
            if revision == settings.max_revisions:
                manifest['stopping_reason'] = 'revision_limit'
                break
            seen.add(signature)
            candidate = stage('revise', lambda: Packet.model_validate(gateway.call('revise', dict(payload,
                packet=packet.model_dump(), findings=[f.model_dump() for f in actionable]))))
            store.event(run_id, 'revision_candidate', {'packet': candidate.model_dump(), 'validation': [f.model_dump() for f in audit(candidate, career)]})
            if digest(candidate.model_dump()) in seen:
                manifest['stopping_reason'] = 'repeated_or_oscillating_output'
                break
            packet = candidate
        manifest['validation'] = [f.model_dump() for f in audit(packet, career)]
        manifest['status'] = 'needs_review' if manifest['validation'] else 'draft'
    except Exception as exc:
        manifest['status'] = 'failed'
        manifest['error_type'] = type(exc).__name__
        manifest['stopping_reason'] = 'stage_failure'
        raise
    finally:
        manifest['updated'] = now()
        manifest['latency'] = time.monotonic()-started
        manifest['telemetry'] = gateway.telemetry
        manifest['estimated_cost'] = (sum(t['estimated_cost'] for t in gateway.telemetry)
            if manifest['status'] != 'failed' and all(t['estimated_cost'] is not None for t in gateway.telemetry) else None)
        store.save(manifest)
    return manifest


def discovery_questions(requirements):
    questions = []
    for q in requirements:
        if q.classification == 'direct':
            continue
        prompt = ('Does this practical constraint work for you? Leave it unresolved if unknown.'
                  if q.kind == 'constraint' else
                  'Is there relevant experience not yet captured? None is a valid answer. '
                  'If yes, describe where/when, what you personally did, actual tool use, '
                  'production versus portfolio setting, ownership, and any supported outcome. '
                  'For metrics, include units, measurement source, baseline, window and uncertainty.')
        questions.append({'requirement_id': q.id, 'excerpt': q.excerpt,
                          'classification': q.classification, 'prompt': prompt,
                          'answer_status': 'unanswered', 'generation_eligible': False})
    return questions
