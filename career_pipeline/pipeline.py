import json
from copy import deepcopy
import re
import time
import uuid
from pathlib import Path
from typing import Protocol
from .models import Career, Requirement, Packet, Finding, Settings
from .providers import Gateway, PROMPT_VERSION
from .store import Store, digest, now
from .review import audit, reviews, document_plan, group_key
from .grounding import accepted_assessments
from .composition import build_composition_plan
from .content_quality import check_content_quality
from .diagnostics import failure_details

TOKENS = re.compile(r'[a-z0-9+#]+')
NAMED_TOOLS = ('sql server', 'azure devops', 'azure data factory', 'azure sql', 'blob storage',
               'power bi', 'kubernetes', 'terraform', 'nuget', 'npm', 'mosaic ai', 'unity catalog')
STOP = {'the','a','an','and','of','to','in','with','for','is','you','we','required','preferred','must','have','experience','using'}

def words(text):
    return set(TOKENS.findall(text.lower())) - STOP

def extract(jd):
    if not 20 <= len(jd.strip()) <= 50000:
        raise ValueError('Job description must contain 20–50,000 characters')
    requirements = []
    priority = 'ambiguous'
    in_requirement_section = False
    headings = {'required': 'required', 'preferred': 'preferred', 'responsibilities': 'ambiguous', 'skills': 'ambiguous', 'qualifications': 'required', 'required qualifications': 'required',
                'requirements': 'required', 'experience': 'required', 'education': 'preferred',
                'preferred experience': 'preferred', 'preferred qualifications': 'preferred',
                'key responsibilities': 'ambiguous', 'job description': 'ambiguous',
                'knowledge, skills, and abilities': 'ambiguous'}
    for raw in jd.splitlines():
        excerpt = raw.strip()
        line = re.sub(r'^\s*(?:[-•*]\s+|\d+[.)]\s+)', '', raw).strip()
        line = re.sub(r'^#{1,6}\s+', '', line).strip('*_ ').strip()
        if not line:
            continue
        low = line.lower().rstrip(':')
        if low in headings:
            priority = headings[low]
            in_requirement_section = True
            continue
        if low in ('overview', 'position summary', 'role summary', 'about the job', 'attributes that will drive success'):
            priority = 'ambiguous'
            in_requirement_section = False
            continue
        if re.match(r'^(company|role|source|user-supplied posting url|url retrieval):', low):
            continue
        is_bullet = bool(re.match(r'^\s*(?:[-•*]\s+|\d+[.)]\s+)', raw))
        requirement_like = bool(re.search(r'\b(experience|proficiency|knowledge|familiarity|ability|degree|python|sql|etl|pipelines?|databricks|snowflake)\b', low)) or bool(re.match(r'^(develop|build|maintain|design|write|support|monitor|collaborate|create|implement)\b', low))
        explicit = re.search(r'\b(required|preferred|must|nice to have)\b', low)
        if not (is_bullet or explicit or low.startswith('location:') or requirement_like or (in_requirement_section and len(line.split()) >= 3)):
            continue
        local = priority
        if re.search(r'\b(preferred|nice to have|bonus)\b', low):
            local = 'preferred'
        elif re.search(r'\b(required|must)\b', low):
            local = 'required'
        requirements.append(Requirement(id=f'q{len(requirements)+1}', text=line, excerpt=excerpt,
            priority=local, kind='constraint' if re.search(r'\b(remote|hybrid|onsite|salary|travel|authorization|location)\b', low) else 'skill'))
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
            approved = words(' '.join(e.supported_wording))
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
        named = [tool for tool in NAMED_TOOLS if re.search(r'(?<![a-z0-9])' + re.escape(tool) + r'(?![a-z0-9])', q.text.lower())]
        if named:
            # Shared brand words such as Azure do not establish a different named service.
            eligible = [m for m in eligible if any(tool in (' '.join(m[0].supported_wording) + ' ' + ' '.join(t.name for t in m[0].technologies)).lower() for tool in named)]
        q.evidence_ids = [m[0].id for m in eligible]
        if eligible:
            q.classification = 'direct' if any(m[2] for m in eligible) else 'transferable'
        elif matches and any(not m[0].eligible for m in matches):
            q.classification = 'needs_clarification'
    return requirements

def load_style(path):
    root = Path(path)
    # Explicitly load the portable skill. Raw examples are never interpolated into instructions.
    skill = (root/'SKILL.md').read_text(encoding='utf-8')
    profile = json.loads((root/'profile.json').read_text(encoding='utf-8'))
    if not profile.get('approved'):
        raise ValueError('Writing profile must be approved or use the labeled neutral default')
    guidance_file = root/'resume_guidance.md'
    guidance = guidance_file.read_text(encoding='utf-8') if guidance_file.exists() else ''
    bundle = {'skill': skill, 'profile': profile, 'resume_guidance': guidance}
    return {'version': profile['version'], 'hash': digest(bundle),
            'guidance_version': (re.search(r'Version: (\S+)', guidance).group(1) if re.search(r'Version: (\S+)', guidance) else 'custom') if guidance else None,
            'instructions': skill + '\n' + guidance + '\n' + json.dumps(profile)}

def validate_review_contract(raw, role, packet, requirements, career, factual_mode):
    """Malformed reviewer output is distinct from a supported negative factual verdict."""
    parsed = [Finding.model_validate(f) for f in raw.get('findings', [])]
    known = {c.id for c in packet.resume + packet.cover_letter}
    qids = {q.id for q in requirements}
    eids = {e.id for e in career.evidence}
    for f in parsed:
        if f.role != role:
            raise ValueError('Reviewer returned findings for the wrong role')
        if f.claim_id and f.claim_id not in known:
            raise ValueError('Reviewer cited an unknown passage')
        if f.requirement_id and f.requirement_id not in qids:
            raise ValueError('Reviewer cited an unknown requirement')
        if not set(f.evidence_ids) <= eids:
            raise ValueError('Reviewer cited unknown evidence')
        if not (f.claim_id or f.section or f.requirement_id):
            raise ValueError('Reviewer finding must identify a passage, section or requirement')
    receipt = set(raw.get('reviewed_claim_ids', []))
    if role == 'evidence' and receipt != known:
        raise ValueError('Evidence reviewer did not account for every claim')
    if role == 'evidence' and factual_mode == 'model_reviewed':
        accepted_assessments(packet, career, raw.get('assessments', []))
    return parsed, receipt


def run(jd, career, store=None, settings=None, style_path='writing_style', strategy='C', seed_packet=None, application=None):
    store = store or Store()
    settings = settings or Settings()
    style = load_style(style_path)
    run_id = str(uuid.uuid4())
    started = time.monotonic()
    manifest = {'id': run_id, 'created': now(), 'updated': now(), 'status': 'running',
        'application': {k: str((application or {}).get(k, '')).strip()[:300] for k in ('company', 'role')},
        'input_hash': digest(jd), 'evidence_hash': digest(career.model_dump(mode='json')),
        'prompt_version': PROMPT_VERSION, 'schema_version': '4', 'style': style,
        'settings': settings.model_dump(), 'strategy': strategy, 'stages': [], 'versions': [],
        'revision_count': 0, 'artifacts': [], 'approved': False,
        'review_mode': settings.reviewer, 'generation_mode': settings.generator,
        'seed_packet_hash': digest(seed_packet.model_dump()) if seed_packet else None,
        'follow_up_answers': store.follow_up_answers(digest(jd))}
    store.save(manifest)
    gateway = Gateway(store, settings)
    def stage(name, function):
        manifest['active_stage'] = name
        ts = time.monotonic()
        try:
            result = function()
            manifest['stages'].append({'name': name, 'status': 'passed', 'latency': time.monotonic()-ts})
            store.save(manifest)
            return result
        except Exception:
            manifest['stages'].append({'name': name, 'status': 'failed', 'latency': time.monotonic()-ts})
            store.save(manifest)
            raise
    try:
        store.event(run_id, 'inputs', {'jd': jd, 'career': career.model_dump(mode='json')})
        requirements = stage('extract', lambda: extract(jd))
        requirements = stage('retrieve', lambda: map_requirements(requirements, career))
        selected = {i for q in requirements for i in q.evidence_ids}
        # Document anchors are explicit: record omission must not hide publications, skills,
        # or an otherwise relevant role simply because its vocabulary lost a top-k contest.
        eligible = [e for e in career.evidence if e.eligible]
        if strategy == 'A':
            selected = {e.id for e in eligible}
        else:
            selected.update(e.id for e in eligible if e.kind in ('publication', 'education', 'skill'))
            matched_groups = {group_key(e)
                              for e in eligible if e.id in selected and e.kind == 'experience'}
            for e in eligible:
                if e.kind == 'experience' and group_key(e) in matched_groups:
                    selected.add(e.id)
            # Retrieval tailors emphasis; it must not erase confirmed career history.
            groups = {}
            for e in eligible:
                if e.kind == 'experience':
                    groups.setdefault(group_key(e), []).append(e)
            query = words(jd)
            for records in groups.values():
                ranked = sorted(records, key=lambda e: (
                    -len(query & words(' '.join(e.supported_wording + e.tags + [t.name for t in e.technologies]))), e.id))
                selected.update(e.id for e in ranked[:career.presentation.minimum_recent_bullets])
        evidence = [e.model_dump(mode='json') for e in eligible if e.id in selected]
        plan = document_plan(career, selected)
        plan['include_cover_letter'] = settings.include_cover_letter
        plan['pending_sources'] = [{'id': e.id, 'kind': e.kind} for e in career.evidence if not e.eligible]
        manifest['composition_plan'] = build_composition_plan(career, selected)
        if not settings.include_cover_letter:
            manifest['composition_plan']['cover_letter_paragraphs'] = []
        manifest['document_plan'] = plan
        manifest['requirements'] = [q.model_dump() for q in requirements]
        manifest['discovery_questions'] = discovery_questions(requirements)
        manifest['selected_evidence'] = [e['id'] for e in evidence]
        manifest['excluded_evidence'] = [{'id': e.id, 'reason': 'uncertain_source' if not e.eligible else 'not_selected'}
                                         for e in career.evidence if e.id not in selected or not e.eligible]
        payload = {'job_description': jd, 'requirements': manifest['requirements'], 'evidence': evidence,
                   'style': style['instructions'], 'document_plan': plan, 'composition_plan': manifest['composition_plan'],
                   'factual_mode': settings.factual_mode}
        packet = seed_packet or stage('generate', lambda: Packet.model_validate(gateway.call('generate', payload)))
        seen = set()
        last_passing = None
        for revision in range(settings.max_revisions + 1):
            signature = digest(packet.model_dump())
            version = {'number': revision, 'packet': packet.model_dump(), 'findings': [],
                       'reviews': {}, 'hash': signature, 'created': now()}
            manifest['versions'].append(version)
            manifest['revision_count'] = revision
            store.save(manifest)  # Save even if a reviewer fails before returning.
            quality = (check_content_quality(packet, career, settings.content_quality, plan) if settings.generator != 'mock' else [])
            version['content_quality_status'] = ('not_assessed_practice' if settings.generator == 'mock' else 'assessed' if settings.content_quality.enabled else 'disabled')
            version['quality_findings'] = [f.model_dump() for f in quality]
            findings = stage('validate', lambda: reviews(packet, requirements, career, plan)) + quality
            version['findings'] = [f.model_dump() for f in findings]
            grounded = set()
            if strategy == 'C':
                for role in ('evidence', 'recruiter', 'voice'):
                    version['reviews'][role] = {'status': 'running', 'provider': settings.reviewer,
                                                'model': settings.reviewer_model, 'mode': settings.reviewer}
                    store.save(manifest)
                    role_payload = dict(payload, packet=packet.model_dump(), role=role,
                        career=career.model_dump(mode='json'))
                    role_payload.pop('evidence', None)  # The full career already contains these records.
                    try:
                        def review_with_correction():
                            attempts = version['reviews'][role].setdefault('attempts', [])
                            request = role_payload
                            for attempt in range(2):
                                raw = gateway.call('review', request)
                                try:
                                    parsed, receipt = validate_review_contract(raw, role, packet, requirements, career, settings.factual_mode)
                                except ValueError as exc:
                                    attempts.append({'status': 'rejected', 'response': raw, 'error': str(exc)})
                                    store.save(manifest)
                                    if attempt or settings.reviewer == 'mock':
                                        raise
                                    request = dict(role_payload, contract_correction={
                                        'error': str(exc),
                                        'claim_ids': [c.id for c in packet.resume + packet.cover_letter],
                                        'evidence_ids': [e.id for e in career.evidence],
                                        'requirement_ids': [q.id for q in requirements],
                                        'instruction': 'Return a complete corrected review for your assigned role. This corrects the response contract, never relaxes factual standards.'})
                                else:
                                    attempts.append({'status': 'accepted', 'response': raw})
                                    return raw, parsed, receipt
                        raw, parsed, receipt = stage('review_' + role, review_with_correction)
                        if role == 'evidence' and settings.factual_mode == 'model_reviewed':
                            version['support_assessments'] = raw.get('assessments', [])
                            grounded, rejected = accepted_assessments(packet, career, version['support_assessments'])
                            version['support_rejections'] = rejected
                            findings = reviews(packet, requirements, career, plan, grounded) + quality
                            for ident, reasons in rejected.items():
                                findings.append(Finding(role='evidence', claim_id=ident, severity='error',
                                    code='grounding_rejected', message='; '.join(reasons)))
                        findings.extend(parsed)
                        version['reviews'][role].update(status='passed', findings=[f.model_dump() for f in parsed],
                                                         reviewed_claim_ids=sorted(receipt))
                    except Exception:
                        version['reviews'][role]['status'] = 'failed'
                        for record in reversed(manifest['stages']):
                            if record['name'] == 'review_' + role:
                                record['status'] = 'failed'
                                break
                        store.save(manifest)
                        raise
                    # Do not hide document-level objections just because a missing section
                    # has no existing passage or requirement ID.
                    version['findings'] = list({digest(f.model_dump()): f.model_dump() for f in findings}.values())
                    store.save(manifest)
            version['findings'] = list({digest(f.model_dump()): f.model_dump() for f in findings}.values())
            store.event(run_id, 'version', version)
            store.save(manifest)
            has_errors = any(f['severity'] == 'error' for f in version['findings'])
            if strategy == 'C' and has_errors and last_passing is not None:
                restored = deepcopy(last_passing)
                restored.update(number=len(manifest['versions']), created=now(),
                                restored_from_version=last_passing['number'])
                manifest['versions'].append(restored)
                store.event(run_id, 'version_restored', {'from_version': last_passing['number'],
                    'rejected_version': version['number'], 'packet_hash': restored['hash']})
                manifest['stopping_reason'] = 'factual_regression_rollback'
                store.save(manifest)
                break
            if strategy == 'C' and not has_errors:
                last_passing = deepcopy(version)
            actionable = [f for f in version['findings'] if f['severity'] in ('error', 'suggestion')]
            if strategy != 'C' or not actionable:
                manifest['stopping_reason'] = 'one_shot' if strategy != 'C' else 'material_issues_resolved'
                break
            if revision == settings.max_revisions:
                manifest['stopping_reason'] = 'revision_limit'
                break
            seen.add(signature)
            candidate = stage('revise', lambda: Packet.model_validate(gateway.call('revise', dict(payload,
                packet=packet.model_dump(), findings=actionable))))
            store.event(run_id, 'revision_candidate', {'packet': candidate.model_dump(),
                'validation': [f.model_dump() for f in audit(candidate, career, include_cover_letter=settings.include_cover_letter)]})
            if digest(candidate.model_dump()) in seen:
                manifest['stopping_reason'] = 'repeated_or_oscillating_output'
                break
            packet = candidate
        final = manifest['versions'][-1]
        final_packet = Packet.model_validate(final['packet'])
        accepted = set()
        if settings.factual_mode == 'model_reviewed':
            accepted, _ = accepted_assessments(final_packet, career, final.get('support_assessments', []))
        manifest['validation'] = [f.model_dump() for f in audit(final_packet, career, accepted, include_cover_letter=settings.include_cover_letter)]
        review_errors = [f for f in final['findings'] if f['severity'] == 'error']
        manifest['status'] = 'needs_review' if manifest['validation'] or review_errors else 'draft'
        manifest['unresolved_findings'] = final['findings']
    except Exception as exc:
        manifest['status'] = 'failed'
        manifest['error_type'] = type(exc).__name__
        manifest['failure'] = dict(failure_details(exc), stage=manifest.get('active_stage', 'setup'))
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
