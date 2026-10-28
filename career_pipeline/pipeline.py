import json
from copy import deepcopy
import re
import time
import uuid
from pathlib import Path
from typing import Protocol
from .models import Career, Requirement, Packet, Finding, Settings
from .providers import Gateway, PROMPT_VERSION, IncompleteResponse
from .store import Store, digest, now
from .review import audit, reviews, document_plan, group_key
from .grounding import accepted_assessments, deterministic_objections, repair_citations
from .composition import build_composition_plan
from .baseline import employment_baseline, ensure_history_bullets
from .content_quality import check_content_quality
from .diagnostics import failure_details
from .text_safety import strip_reference_codes
from .duplicates import hidden_duplicates

TOKENS = re.compile(r'[a-z0-9+#]+')
NAMED_TOOLS = ('sql server', 'azure devops', 'azure data factory', 'azure sql', 'blob storage',
               'power bi', 'kubernetes', 'terraform', 'nuget', 'npm', 'mosaic ai', 'unity catalog')
STOP = {'the','a','an','and','of','to','in','with','for','is','you','we','required','preferred','must','have','experience','using'}
GAP_CLASSIFICATIONS = ('unsupported', 'needs_clarification')
REVIEW_LIMITS = {'recruiter': 8, 'voice': 6}
# Pasted or imported postings often carry the job board's page around them. Boilerplate
# sections end the requirement list; job-board listings after the posting end extraction.
POSTING_BOILERPLATE = re.compile(r'^(benefits|perks|what we offer|the company|about (us|the company|[a-z0-9&.,\' -]{2,40})|'
    r'industry recognition|culture|our (culture|values|mission)|how to apply|equal (employment )?opportunity|'
    r'commitment equal opportunity.*|eeo statement|compensation|pay transparency)$')
POSTING_END = re.compile(r'^(people also viewed|similar jobs|show more jobs like this|more jobs like this|'
    r'referrals increase your chances|seniority level|explore top content|get notified about new)\b')
PAGE_CHROME = re.compile(r'^(\d+\+? (second|minute|hour|day|week|month|year)s? ago|[\d,]+ open jobs|'
    r'(sign in|join now|agree & join|email or phone|password|forgot password\??|see who you know|'
    r'show|save|apply|report this job)\b.*|.*\bsign in\b.*|by clicking continue\b.*|.{1,60} jobs)$')
# Legal and application boilerplate says "must"/"required" without stating a job requirement.
POSTING_LEGAL = re.compile(r'\b(equal (employment )?opportunity|protected veterans?|self-identify|vevraa|'
    r'reasonable accommodations?|essential (duty|duties|functions)|click (on )?the|to apply\b|apply button|'
    r'apply (through|via|on|now)\b|get in touch|interested in this (opportunity|role|position))')
SECTION_HEADING = re.compile(r'(?:required|preferred|minimum|basic|desired|additional|key|nice[- ]to[- ]have)?\s*'
    r'(?:technical\s+|soft\s+|professional\s+)?(?:qualifications?|requirements?|skills|responsibilities|duties|'
    r'experience|education|education and experience)(?:\s+added by the job poster)?')
REQUIREMENT_START = re.compile(r'^(experience|proficiency|knowledge|familiarity|ability|strong|demonstrated|'
                               r'bachelor|master|degree|working|hands-on|understanding|exposure|\d)')


def heading_priority(text):
    if re.search(r'\b(preferred|nice[- ]to[- ]have|desired|bonus|plus)\b', text):
        return 'preferred'
    if re.search(r'\b(required|minimum|basic|qualifications?|requirements?|must)\b', text):
        return 'required'
    return 'ambiguous'


def section_heading(line, raw):
    """'required'/'preferred'/'ambiguous' when the line names a section, 'subheading' for a
    numbered title inside one, None for ordinary text. Job boards often lose the newline after
    a colon, e.g. 'Required Qualifications:Education and Experience'."""
    low = line.lower().strip()
    if ':' in low:
        left, right = (part.strip() for part in low.split(':', 1))
        if SECTION_HEADING.fullmatch(left) and len(right.split()) <= 6 and not right.endswith('.'):
            return heading_priority(left)
    if len(low.split()) <= 6 and SECTION_HEADING.fullmatch(low.rstrip(':')):
        return heading_priority(low)
    words_ = line.split()
    if (re.match(r'^\s*\d+[.)]\s', raw) and len(words_) <= 8 and not re.search(r'[.,;]', line)
            and not REQUIREMENT_START.match(low)):
        long_words = [w for w in words_ if len(w) > 3]
        if long_words and sum(w[0].isupper() for w in long_words) / len(long_words) >= 0.6:
            return 'subheading'
    return None

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
                'knowledge, skills, and abilities': 'ambiguous', 'clearance requirement': 'required'}
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
        if POSTING_END.match(low):
            break
        if len(line.split()) <= 6 and POSTING_BOILERPLATE.match(low):
            priority = 'ambiguous'
            in_requirement_section = False
            continue
        if PAGE_CHROME.match(low) or POSTING_LEGAL.search(low):
            continue
        heading = section_heading(line, raw)
        if heading == 'subheading':
            continue
        if heading:
            priority = heading
            in_requirement_section = True
            continue
        tokens = line.split()
        if sum(t.startswith('#') for t in tokens) >= max(2, len(tokens) // 2) or len(tokens) > 60:
            continue  # Hashtag lines and descriptive paragraphs are not individual requirements.
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
            priority=local, kind='constraint' if re.search(r'\b(remote|hybrid|onsite|salary|travel|authorization|location|'
                r'citizen|citizenship|green card|permanent resident|clearance|public trust)\b', low) else 'skill'))
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

def match_payload(requirements, career):
    """Concise evidence for requirement matching: statements and tools, not audit metadata."""
    evidence = [{'id': e.id, 'kind': e.kind, 'project': e.project, 'employer': e.employer,
                 'title': e.official_title, 'statements': e.supported_wording,
                 'tools': [f'{t.name} ({t.context})' for t in e.technologies]}
                for e in career.evidence if e.eligible]
    return {'requirements': [{'id': q.id, 'text': q.text, 'priority': q.priority}
                             for q in requirements if q.kind == 'skill'],
            'evidence': evidence, 'style': ''}


def apply_matches(requirements, result, career):
    """Replace word-overlap matches with validated model judgments; drop non-requirements."""
    eligible = {e.id for e in career.evidence if e.eligible}
    by_id = {m['requirement_id']: m for m in result.get('matches', [])}
    kept, dropped = [], []
    for q in requirements:
        m = by_id.get(q.id)
        if q.kind == 'constraint' or not m:
            kept.append(q)  # Unanswered requirements keep their word-overlap classification.
            continue
        if m['classification'] == 'not_a_requirement':
            dropped.append(q.id)
            continue
        ids = [i for i in dict.fromkeys(m['evidence_ids']) if i in eligible][:3]
        classification = m['classification'] if ids else 'unsupported'
        q.classification = classification
        q.evidence_ids = ids if classification != 'unsupported' else []
        q.rationale = strip_reference_codes(' '.join(m['rationale'].split()), eligible)[:300] or None
        kept.append(q)
    return kept, dropped


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
        if role != 'evidence' and f.severity == 'error':
            # Presentation reviewers advise; only factual auditing and deterministic checks block approval.
            f.severity = 'suggestion'
    if role in REVIEW_LIMITS:
        parsed = parsed[:REVIEW_LIMITS[role]]  # Most important first; a long list is not actionable.
    receipt = set(raw.get('reviewed_claim_ids', []))
    if role == 'evidence' and receipt != known:
        raise ValueError('Evidence reviewer did not account for every claim')
    if role == 'evidence' and factual_mode == 'model_reviewed':
        _, rejected = accepted_assessments(packet, career, raw.get('assessments', []))
        quote_errors = {'not every cited record has an exact supporting quote', 'supporting quote is not present in the source'}
        for assessment in raw.get('assessments', []):
            # A positive verdict with malformed quotations is a response-contract error,
            # not a reason to rewrite otherwise-supported source facts.
            if all(assessment.get(key) for key in ('wording_supported', 'metrics_consistent',
                    'technology_consistent', 'scope_consistent', 'dates_titles_consistent')) and (
                    quote_errors & set(rejected.get(assessment['claim_id'], []))):
                raise ValueError('Auditor supplied incomplete or nonliteral supporting quotes')
    return parsed, receipt


def batched_evidence_review(packet, payload, review_one, output_limit, records):
    """Bound response size without dropping claims; split truncated groups down to one.

    All requests still pass through Gateway budgets and the per-batch review contract.
    Recruiter/voice reviews retain the complete document for cross-passage judgments.
    """
    all_claims = packet.resume + packet.cover_letter
    exact = set()
    if payload.get('factual_mode') == 'model_reviewed':
        career = Career.model_validate(payload['career'])
        index = {e.id:e for e in career.evidence}
        exact = {c.id for c in all_claims if all(i in index and index[i].eligible
                 and c.text in index[i].supported_wording for i in c.evidence_ids)}
    claims = [c for c in all_claims if c.id not in exact]
    if exact:
        records.append({'claim_ids':sorted(exact), 'status':'passed', 'method':'exact_source_comparison'})
    group_size = max(1, min(4, output_limit // 1400))
    combined = {'findings': [], 'reviewed_claim_ids': sorted(exact), 'assessments': []}

    def process(group):
        ids = {c.id for c in group}
        subset = Packet(resume=[c for c in packet.resume if c.id in ids],
            cover_letter=[c for c in packet.cover_letter if c.id in ids],
            skills=packet.skills if not claims or claims[0].id in ids else [])
        linked = {i for c in group for i in c.evidence_ids} | set(subset.skills)
        career = dict(payload['career'], evidence=[e for e in payload['career']['evidence'] if e['id'] in linked])
        request = dict(role='evidence', packet=subset.model_dump(), career=career, style='',
            requirements=[], factual_mode=payload['factual_mode'],
            application_context=payload.get('job_description', '') if subset.cover_letter else '',
            document_plan={'include_cover_letter': payload['document_plan'].get('include_cover_letter', True),
                           'publications': [], 'education': [], 'experience_groups': [], 'skill_evidence': []},
            review_scope='Evidence review batch: inspect only the supplied claims. Other claims are reviewed separately; do not flag missing sections.')
        record = {'claim_ids': [c.id for c in group], 'status': 'running'}
        records.append(record)
        try:
            raw, _, _ = review_one(subset, request)
        except IncompleteResponse:
            record['status'] = 'incomplete'
            if len(group) <= 1:
                raise
            middle = len(group) // 2
            process(group[:middle])
            process(group[middle:])
            return
        except Exception:
            record['status'] = 'failed'
            raise
        record['status'] = 'passed'
        for key in combined:
            combined[key].extend(raw.get(key, []))

    for start in range(0, len(claims) if exact else max(1, len(claims)), group_size):
        process(claims[start:start + group_size])
    return combined


def run(jd, career, store=None, settings=None, style_path='writing_style', strategy='C', seed_packet=None, application=None,
        on_stage=None):
    """on_stage(name, revision) is called as each stage starts, for progress display only."""
    store = store or Store()
    settings = settings or Settings()
    style = load_style(style_path)
    run_id = str(uuid.uuid4())
    started = time.monotonic()
    manifest = {'id': run_id, 'created': now(), 'updated': now(), 'status': 'running',
        'application': {k: str((application or {}).get(k, '')).strip()[:300] for k in ('company', 'role')},
        'input_hash': digest(jd), 'evidence_hash': digest(career.model_dump(mode='json')),
        'prompt_version': PROMPT_VERSION, 'schema_version': '6', 'employment_baseline': employment_baseline(career), 'style': style,
        'settings': settings.model_dump(), 'strategy': strategy, 'stages': [], 'versions': [],
        'revision_count': 0, 'artifacts': [], 'approved': False,
        'review_mode': settings.reviewer, 'generation_mode': settings.generator,
        'seed_packet_hash': digest(seed_packet.model_dump()) if seed_packet else None,
        'follow_up_answers': store.follow_up_answers(digest(jd))}
    store.save(manifest)
    gateway = Gateway(store, settings)
    def stage(name, function):
        manifest['active_stage'] = name
        if on_stage:
            on_stage(name, manifest['revision_count'])
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
    last_passing = None
    try:
        store.event(run_id, 'inputs', {'jd': jd, 'career': career.model_dump(mode='json')})
        stage('baseline_sources', lambda: ensure_history_bullets(Packet(resume=[], cover_letter=[]), career))
        requirements = stage('extract', lambda: extract(jd))
        requirements = stage('retrieve', lambda: map_requirements(requirements, career))
        manifest['requirement_matching'] = {'method': 'word_overlap'}
        if settings.generator != 'mock' and any(q.kind == 'skill' for q in requirements):
            try:
                result = stage('match', lambda: gateway.call('match', match_payload(requirements, career)))
                requirements, dropped = apply_matches(requirements, result, career)
                manifest['requirement_matching'] = {'method': 'model', 'model': settings.generator_model,
                                                    'dropped_non_requirements': dropped}
            except Exception as exc:
                # Matching improves emphasis and gap reporting; word overlap remains a usable fallback.
                manifest['requirement_matching'] = {'method': 'word_overlap', 'model_failure': failure_details(exc)}
        selected = {i for q in requirements for i in q.evidence_ids}
        # Document anchors are explicit: record omission must not hide publications, skills,
        # or an otherwise relevant role simply because its vocabulary lost a top-k contest.
        # A degree or publication saved twice in different formats is rendered once.
        hidden = hidden_duplicates(career)
        selected -= hidden
        eligible = [e for e in career.evidence if e.eligible and e.id not in hidden]
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
        else:
            # Anchor the letter to the posting's best-matched requirements rather than a tour of
            # all experience. Degrees and years-of-experience lines make poor letter themes.
            index = {e.id: e for e in career.evidence}
            themes = [q for q in requirements if q.kind == 'skill' and q.classification in ('direct', 'transferable')
                      and q.evidence_ids and not re.search(r'\b(years?|degree|bachelor|master)\b', q.text.lower())
                      and any(i in index and index[i].kind != 'education' for i in q.evidence_ids)]
            themes.sort(key=lambda q: (q.classification != 'direct', q.priority == 'preferred'))
            manifest['composition_plan']['letter_focus'] = [
                {'requirement': q.text, 'evidence_ids': q.evidence_ids, 'why': q.rationale} for q in themes[:3]]
        plan['employment_baseline'] = manifest['employment_baseline']
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
        original_claims = {c.id for c in packet.resume}
        packet = stage('baseline_bullets', lambda: ensure_history_bullets(packet, career))
        manifest['baseline_restored_claims'] = [c.id for c in packet.resume if c.id not in original_claims]
        augment = settings.factual_mode == 'model_reviewed'  # Strict mode needs every cited record's exact wording.
        packet, repairs = repair_citations(packet, career, augment)
        manifest['citation_repairs'] = [dict(r, version=0) for r in repairs]
        def review_role(role, version, packet, findings, advisory, quality):
            """Run one reviewer on a version; returns updated findings and newly grounded claim IDs."""
            grounded = set()
            version['reviews'][role] = {'status': 'running', 'provider': settings.reviewer,
                                        'model': settings.reviewer_model, 'mode': settings.reviewer}
            store.save(manifest)
            role_payload = dict(payload, packet=packet.model_dump(), role=role,
                career=career.model_dump(mode='json'))
            role_payload.pop('evidence', None)  # The full career already contains these records.
            if role != 'evidence' and settings.reviewer != 'mock':
                # Factual auditing already has full source context. Presentation editors
                # need concise source summaries, not repeated transcripts and audit data.
                summaries = []
                for e in role_payload['career']['evidence']:
                    summaries.append({k: e[k] for k in ('id', 'kind', 'project', 'employment_ids',
                        'employer', 'official_title', 'ownership', 'technologies', 'confirmed_statements', 'approved_wording')}
                        | {'actions': [], 'sources': [dict(reference='Saved source ' + e['id'], status=source['status'])
                                                    for source in e['sources']]})
                role_payload['career']['evidence'] = summaries
                role_payload.pop('composition_plan', None)
                if role == 'voice':
                    role_payload.pop('job_description', None)
                    role_payload['requirements'] = []
                    role_payload['document_plan'] = {'include_cover_letter': settings.include_cover_letter,
                        'publications': [], 'education': [], 'experience_groups': [], 'skill_evidence': []}
            try:
                def review_one(request_packet, request_payload):
                    attempts = version['reviews'][role].setdefault('attempts', [])
                    request = request_payload
                    for attempt in range(2):
                        raw = gateway.call('review', request)
                        try:
                            parsed, receipt = validate_review_contract(raw, role, request_packet, requirements, career, settings.factual_mode)
                        except ValueError as exc:
                            attempts.append({'status': 'rejected', 'response': raw, 'error': str(exc), 'claim_ids': [c.id for c in request_packet.resume + request_packet.cover_letter]})
                            store.save(manifest)
                            if attempt or settings.reviewer == 'mock':
                                raise
                            request = dict(request_payload, contract_correction={
                                'error': str(exc),
                                'claim_ids': [c.id for c in request_packet.resume + request_packet.cover_letter],
                                'evidence_ids': [e.id for e in career.evidence],
                                'requirement_ids': [q.id for q in requirements],
                                'instruction': 'Return a complete corrected review for your assigned role. This corrects the response contract, never relaxes factual standards.'})
                        else:
                            attempts.append({'status': 'accepted', 'response': raw})
                            store.save(manifest)
                            return raw, parsed, receipt
                def review_with_correction():
                    if role == 'evidence' and settings.reviewer != 'mock':
                        combined = batched_evidence_review(packet, role_payload, review_one,
                            settings.max_output_tokens, version['reviews'][role].setdefault('batches', []))
                        parsed, receipt = validate_review_contract(combined, role, packet, requirements, career, settings.factual_mode)
                        return combined, parsed, receipt
                    return review_one(packet, role_payload)
                raw, parsed, receipt = stage('review_' + role, review_with_correction)
                if role == 'evidence' and settings.factual_mode == 'model_reviewed':
                    version['support_assessments'] = raw.get('assessments', [])
                    grounded, rejected = accepted_assessments(packet, career, version['support_assessments'])
                    exact_ids = {ident for batch in version['reviews'][role].get('batches', [])
                                 if batch.get('method') == 'exact_source_comparison' for ident in batch['claim_ids']}
                    grounded.update(exact_ids)
                    version['reviews'][role]['deterministic_claim_ids'] = sorted(exact_ids)
                    version['reviews'][role]['model_reviewed_claim_ids'] = sorted(receipt - exact_ids)
                    version['support_rejections'] = rejected
                    findings = reviews(packet, requirements, career, plan, grounded) + quality
                    for ident, reasons in rejected.items():
                        findings.append(Finding(role='evidence', claim_id=ident, severity='error',
                            code='grounding_rejected', message='; '.join(reasons)))
                if role != 'evidence':
                    deterministic = {digest(f.model_dump()) for f in findings} - advisory
                    # Reviewer-labelled rewrites use existing facts and may be applied; other
                    # advice (often a request for new facts) stays with the user.
                    advisory.update(key for key in (digest(f.model_dump()) for f in parsed if f.code != 'rewrite')
                                    if key not in deterministic)
                findings.extend(parsed)
                version['reviews'][role].update(status='passed', findings=[f.model_dump() for f in parsed],
                                                 reviewed_claim_ids=sorted(receipt))
            except Exception as exc:
                version['reviews'][role]['status'] = 'failed'
                for record in reversed(manifest['stages']):
                    if record['name'] == 'review_' + role:
                        record['status'] = 'failed'
                        break
                store.save(manifest)
                if role == 'evidence':
                    raise
                # Presentation advice is optional for a draft: keep the factually reviewed
                # packet, and let the approval gate require a rerun that completes this review.
                details = failure_details(exc)
                version['reviews'][role]['failure'] = details
                findings.append(Finding(role=role, section='review', severity='gap', code='review_unavailable',
                    message=f'The {role} review did not complete ({details["code"]}). '
                            'The draft remains available; rerun to complete all reviews before approval.'))
                store.event(run_id, 'review_unavailable', {'version': version['number'], 'role': role,
                                                           'code': details['code']})
            return findings, grounded

        seen = set()
        rewrites_applied = False
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
            preflight = []
            advisory = set()  # Model-only recruiter/voice suggestions: shown to the user, never sent to revision.
            if strategy == 'C' and settings.factual_mode == 'model_reviewed':
                preflight.extend(f for f in findings if f.code in ('invalid_document_character', 'reference_in_text'))
                index = {e.id: e for e in career.evidence}
                for claim in packet.resume + packet.cover_letter:
                    linked = [index[i] for i in claim.evidence_ids if i in index]
                    for reason in deterministic_objections(claim.text, linked):
                        preflight.append(Finding(role='evidence', claim_id=claim.id,
                            evidence_ids=claim.evidence_ids, severity='error', code='grounding_rejected',
                            # Reasons that already say how to fix themselves need no generic advice.
                            message=reason + ('.' if '(' in reason or ';' in reason else
                                '. Remove the unsupported detail or cite a source that actually establishes it; a project label alone is not supporting evidence.')))
                if preflight:
                    # Repair known factual errors before paying for semantic/presentation reviews.
                    # Unassessed paraphrases are not themselves factual errors in this mode.
                    findings = [f for f in findings if f.code != 'unsupported_wording'] + preflight
                    version['reviews'] = {role: {'status':'skipped', 'reason':'deterministic_factual_errors',
                                                 'provider':settings.reviewer, 'model':settings.reviewer_model,
                                                 'mode':settings.reviewer}
                                          for role in ('evidence','recruiter','voice')}
            if strategy == 'C' and not preflight:
                for role in ('evidence', 'recruiter', 'voice'):
                    findings, found = review_role(role, version, packet, findings, advisory, quality)
                    grounded |= found
                    # Do not hide document-level objections just because a missing section
                    # has no existing passage or requirement ID.
                    version['findings'] = list({digest(f.model_dump()): f.model_dump() for f in findings}.values())
                    store.save(manifest)
            version['findings'] = list({digest(f.model_dump()): f.model_dump() for f in findings}.values())
            store.event(run_id, 'version', version)
            store.save(manifest)
            has_errors = any(f['severity'] == 'error' for f in version['findings'])
            incomplete = strategy == 'C' and not preflight and any(
                version['reviews'].get(role, {}).get('status') != 'passed' for role in ('evidence', 'recruiter', 'voice'))
            if strategy == 'C' and (has_errors or incomplete) and last_passing is not None:
                restored = deepcopy(last_passing)
                restored.update(number=len(manifest['versions']), created=now(),
                                restored_from_version=last_passing['number'])
                manifest['versions'].append(restored)
                store.event(run_id, 'version_restored', {'from_version': last_passing['number'],
                    'rejected_version': version['number'], 'packet_hash': restored['hash']})
                manifest['stopping_reason'] = 'factual_regression_rollback' if has_errors else 'review_unavailable_rollback'
                store.save(manifest)
                break
            if strategy == 'C' and not has_errors and not preflight and not incomplete:
                last_passing = deepcopy(version)
            # Model-only presentation suggestions often ask for experience the sources do not
            # establish; revising toward them invites unsupported claims, so they stay with the user.
            # Reviewer rewrites are applied in one revision pass, so reviewers cannot keep the
            # rewriter busy with fresh stylistic preferences every round.
            actionable = [f for f in version['findings'] if f['severity'] == 'error'
                          or (f['severity'] == 'suggestion' and digest(f) not in advisory
                              and not (f.get('code') == 'rewrite' and rewrites_applied))]
            if strategy != 'C' or not actionable:
                manifest['stopping_reason'] = ('one_shot' if strategy != 'C' else
                                               'review_unavailable' if incomplete else 'material_issues_resolved')
                break
            if revision == settings.max_revisions:
                manifest['stopping_reason'] = 'revision_limit'
                break
            seen.add(signature)
            candidate = stage('revise', lambda: Packet.model_validate(gateway.call('revise', dict(payload,
                packet=packet.model_dump(), findings=actionable))))
            rewrites_applied = rewrites_applied or any(f.get('code') == 'rewrite' for f in actionable)
            if last_passing is None and grounded:
                previous_claims = {c.id: c for c in packet.resume + packet.cover_letter}
                index = {e.id: e for e in career.evidence}
                for section in ('resume', 'cover_letter'):
                    for position, claim in enumerate(getattr(candidate, section)):
                        if claim.id in grounded and claim.id in previous_claims:
                            linked = [index[i] for i in claim.evidence_ids if i in index]
                            objections = deterministic_objections(claim.text, linked)
                            if objections:
                                getattr(candidate, section)[position] = previous_claims[claim.id].model_copy(deep=True)
                                manifest.setdefault('revision_restored_claims', []).append({
                                    'revision': revision + 1, 'claim_id': claim.id,
                                    'reason': objections, 'from_version': version['number']})
            before_baseline = {c.id for c in candidate.resume}
            candidate = ensure_history_bullets(candidate, career)
            candidate, repairs = repair_citations(candidate, career, augment)
            manifest['citation_repairs'] += [dict(r, version=revision + 1) for r in repairs]
            manifest['baseline_restored_claims'].extend(c.id for c in candidate.resume if c.id not in before_baseline)
            store.event(run_id, 'revision_candidate', {'packet': candidate.model_dump(),
                'validation': [f.model_dump() for f in audit(candidate, career, include_cover_letter=settings.include_cover_letter)]})
            if digest(candidate.model_dump()) in seen:
                manifest['stopping_reason'] = 'repeated_or_oscillating_output'
                break
            packet = candidate
        final = manifest['versions'][-1]
        if strategy == 'C' and final.get('reviews', {}).get('recruiter', {}).get('reason') == 'deterministic_factual_errors':
            # Fact errors skip paid reviews on intermediate versions, but the version the user
            # receives still gets recruiter and writing feedback. Approval stays blocked by the errors.
            findings = [Finding.model_validate(f) for f in final['findings']]
            for role in ('recruiter', 'voice'):
                findings, _ = review_role(role, final, Packet.model_validate(final['packet']), findings, set(), [])
            final['findings'] = list({digest(f.model_dump()): f.model_dump() for f in findings}.values())
            final['presentation_reviewed_with_fact_errors'] = True
            store.save(manifest)
        final_packet = Packet.model_validate(final['packet'])
        accepted = set()
        if settings.factual_mode == 'model_reviewed':
            accepted, _ = accepted_assessments(final_packet, career, final.get('support_assessments', []))
        manifest['validation'] = [f.model_dump() for f in audit(final_packet, career, accepted, include_cover_letter=settings.include_cover_letter)]
        review_errors = [f for f in final['findings'] if f['severity'] == 'error'
                         or f.get('code') == 'review_unavailable']
        manifest['status'] = 'needs_review' if manifest['validation'] or review_errors else 'draft'
        manifest['unresolved_findings'] = final['findings']
    except Exception as exc:
        if last_passing is not None:
            # A later optional revision must not turn an already reviewed packet into
            # an unusable run. Preserve both the unfinished attempt and the restored version.
            budget = str(exc) == 'provider call/token budget exhausted before request'
            restored = deepcopy(last_passing)
            restored.update(number=len(manifest['versions']), created=now(),
                            restored_from_version=last_passing['number'])
            manifest['versions'].append(restored)
            manifest['budget_stop' if budget else 'restored_after_failure'] = dict(
                failure_details(exc), stage=manifest.get('active_stage', 'setup'))
            manifest['stopping_reason'] = ('budget_limit_restored_reviewed_version' if budget
                                           else 'stage_failure_restored_reviewed_version')
            final_packet = Packet.model_validate(restored['packet'])
            accepted, _ = accepted_assessments(final_packet, career, restored.get('support_assessments', []))
            manifest['validation'] = [f.model_dump() for f in audit(final_packet, career, accepted,
                include_cover_letter=settings.include_cover_letter)]
            manifest['unresolved_findings'] = restored['findings']
            manifest['status'] = 'needs_review' if manifest['validation'] else 'draft'
            store.event(run_id, 'version_restored', {'from_version':last_passing['number'],
                        'reason':'budget_limit' if budget else 'stage_failure', 'packet_hash':restored['hash']})
        else:
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
        # Only real gaps get a question; a transferable match already has evidence to work from.
        if q.kind == 'constraint' or q.classification not in GAP_CLASSIFICATIONS:
            continue
        prompt = ('Is there relevant experience not yet captured? None is a valid answer. '
                  'If yes, describe where/when, what you personally did, actual tool use, '
                  'production versus portfolio setting, ownership, and any supported outcome. '
                  'For metrics, include units, measurement source, baseline, window and uncertainty.')
        questions.append({'requirement_id': q.id, 'excerpt': q.excerpt,
                          'classification': q.classification, 'prompt': prompt,
                          'answer_status': 'unanswered', 'generation_eligible': False})
    return questions
