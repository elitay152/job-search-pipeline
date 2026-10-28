"""Validate a live auditor's semantic assessments plus independent deterministic guardrails.

This is an auditable model judgment, not a proof of entailment or a guarantee of correctness.
Strict mode remains available. Mock reviews cannot authorize paraphrases.
"""
import json
import re
from .models import ClaimAssessment

TOOLS = ('python','pyspark','snowflake','sql server','databricks','power bi','dbt','kubernetes',
         'terraform','docker','scala','java','azure data factory','azure sql','blob storage',
         'azure functions','synapse','mosaic ai','unity catalog','nuget','npm','c#','.net')
# Any form of the verb in a source supports the past tense in a bullet ("Lead weekly
# deployments" on a resume supports "Led weekly deployments").
OWNERSHIP_VERBS = {'owned': r'\bown(?:s|ed|ing)?\b', 'led': r'\b(?:led|lead|leads|leading)\b',
                   'managed': r'\bmanag(?:e|es|ed|ing)\b', 'supervised': r'\bsupervis(?:e|es|ed|ing)\b',
                   'directed': r'\bdirect(?:s|ed|ing)\b', 'architected': r'\barchitect(?:s|ed|ing)\b'}


def numbers(text):
    clean = text.lower().replace(',', '')
    # Normalize readable magnitude words and scientific notation without changing values.
    pattern = r'(?<![\w.])([0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?)\s*(thousand|million|billion|[kmb])?(?!\w)'
    factors = {'k':1000, 'thousand':1000, 'm':1000000, 'million':1000000,
               'b':1000000000, 'billion':1000000000, '':1}
    return {float(n) * factors[unit] for n, unit in re.findall(pattern, clean)}


def qualified_number(text, value, qualifier):
    """Bind uncertainty to this number, not another metric later in the paragraph."""
    clean = text.lower().replace(',', '')
    pattern = r'(?<![\w.])([0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?)\s*(thousand|million|billion|[kmb])?(?!\w)'
    factors = {'k':1000, 'thousand':1000, 'm':1000000, 'million':1000000,
               'b':1000000000, 'billion':1000000000, '':1}
    previous_end = 0
    found = []
    for match in re.finditer(pattern, clean):
        if float(match[1]) * factors[match[2] or ''] == value:
            prefix = clean[max(previous_end, match.start()-100):match.start()]
            # Accept an explicit parenthetical qualifier immediately following the value/unit.
            suffix = clean[match.end():match.end()+50]
            found.append(bool(re.search(r'\b(' + qualifier + r')\b', prefix)
                or re.match(r'\s*(?:[a-z/-]+\s*){0,2}\((' + qualifier + r')\)', suffix)))
        previous_end = match.end()
    return all(found) if found else bool(re.search(r'\b(' + qualifier + r')\b', clean))


def source_text(e):
    return '\n'.join(e.supported_wording + [s.excerpt for s in e.sources if s.excerpt] +
                     [json.dumps(e.fact_details, ensure_ascii=False), json.dumps([m.model_dump() for m in e.metrics]),
                      ' '.join(t.name + ' ' + t.usage for t in e.technologies)])



def delivery_scope_objections(text, linked):
    """Check two common scope upgrades without treating tool co-occurrence as support.

    A deployment through CI/CD does not establish workflow authorship. A training
    topic must occur in a source training statement, not elsewhere in the project.
    These deliberately narrow checks complement the semantic review.
    """
    source = '\n'.join(source_text(e) for e in linked).lower()
    low = text.lower()
    issues = []
    authoring = (r'\b(?:implement(?:ed|ing)?|build(?:ing)?|built|creat(?:ed|ing)|'
                 r'design(?:ed|ing)?|author(?:ed|ing)?|develop(?:ed|ing)?)\b'
                 r'[^.;\n]{0,65}\b(?:ci/cd|ci-cd|continuous integration|github actions)'
                 r'(?:\s+(?:pipelines?|workflows?))?')
    def asserts_authorship(value):
        return any(not re.search(r'\b(?:through|via|using|with)\b', match[0])
                   for match in re.finditer(authoring, value))
    if asserts_authorship(low) and not asserts_authorship(source):
        issues.append('deployment use upgraded to CI/CD authorship')
    # Restrict the check to explicit peer/colleague training and explicit topics.
    training = (r'\b(?:train(?:ed|ing)?|taught|teach(?:ing)?)\b'
                r'[^.;\n]{0,60}\b(?:colleagues?|peers?|coworkers?|team members?)\b'
                r'[^.;\n]{0,15}\b(?:on|in|about)\s+([^.;\n]+)')
    topic_groups = {
        'deployment': r'\bdeploy\w*\b',
        'optimization': r'\boptimi[sz]\w*\b',
        'security': r'\bsecur\w*\b',
        **{tool: r'(?<![a-z0-9])' + re.escape(tool) + r'(?![a-z0-9])' for tool in TOOLS},
    }
    source_topics = ' '.join(re.findall(training, source) +
        re.findall(r'\bpeer training\s+(?:on|in|about)\s+([^.;\n]+)', source))
    for topics in re.findall(training, low):
        for label, pattern in topic_groups.items():
            if re.search(pattern, topics) and not re.search(pattern, source_topics):
                issues.append('unestablished peer-training topic: ' + label)
    return issues


def _repairable(objection):
    """The tool named by an objection that citing a better record can resolve.

    Ownership verbs are never repaired this way: "led" belongs to one piece of work, and
    another record that mentions leading something else does not support it."""
    match = re.match(r'unestablished technology: (.+)$', objection)
    return match.group(1) if match else None


def _states(e, tool):
    return bool(re.search(r'(?<![a-z0-9])' + re.escape(tool) + r'(?![a-z0-9])', source_text(e).lower()))


def repair_citations(packet, career, augment=True):
    """Fix citations before a claim is called unsupported.

    The model sometimes cites a neighbouring record instead of the one that states a tool or
    or cites an ID that is not a record at all. Unknown IDs are dropped. With augment, a
    record that states the missing tool is added: for resume bullets only a record about the
    same project and job; for letter sentences, which summarize skills, a record from the
    named employer (any if none is named). A skill is never moved to another employer or
    accomplishment. An addition is kept only if it removes the objection without raising
    another. Returns the packet and a repair log.
    """
    index = {e.id: e for e in career.evidence}
    employer_by_job = {j.id: j.employer.lower() for j in career.employments}

    def employers(e):
        return {employer_by_job.get(j, '') for j in e.employment_ids} | {e.employer.lower()} - {''}
    result = packet.model_copy(deep=True)
    repairs = []
    for section in ('resume', 'cover_letter'):
        for claim in getattr(result, section):
            unknown = [i for i in claim.evidence_ids if i not in index]
            if unknown and len(unknown) < len(claim.evidence_ids):
                claim.evidence_ids = [i for i in claim.evidence_ids if i in index]
                repairs.append({'claim_id': claim.id, 'removed_unknown': unknown})
            linked = [index[i] for i in claim.evidence_ids if i in index]
            if not augment or not linked:
                continue
            jobs = {j for e in linked for j in e.employment_ids}
            projects = {e.project for e in linked}
            named = {name for name in employer_by_job.values() if name and name in claim.text.lower()}

            def allowed(e):
                if not e.eligible or e.id in claim.evidence_ids:
                    return False
                if section == 'resume':
                    return e.project in projects and bool(jobs & set(e.employment_ids))
                return bool(employers(e) & named) if named else True
            current = deterministic_objections(claim.text, linked)
            for objection in list(current):
                tool = _repairable(objection)
                if not tool or objection not in current:
                    continue
                for e in sorted((e for e in career.evidence if allowed(e) and _states(e, tool)),
                                key=lambda e: (e.kind != 'experience', e.id)):
                    trial = deterministic_objections(claim.text, linked + [e])
                    if set(trial) < set(current):
                        linked.append(e)
                        claim.evidence_ids.append(e.id)
                        current = trial
                        repairs.append({'claim_id': claim.id, 'added': e.id, 'resolves': objection.split(' (')[0]})
                        break
    return result, repairs


def deterministic_objections(text, linked):
    source = '\n'.join(source_text(e) for e in linked)
    low, original = text.lower(), source.lower()
    issues = delivery_scope_objections(text, linked)
    employers = {e.employer.strip().lower() for e in linked if e.employer.strip()}
    heading_prefix = any(re.match(re.escape(name) + r'\s*(?:[:—–(-]|\s+[—–-])', low) for name in employers)
    if heading_prefix:
        issues.append('starts with the employer/title/dates already shown in the role heading; begin with the action instead')
    extra = numbers(text) - numbers(source)
    if extra:
        years = all(1950 <= n <= 2100 and n == int(n) for n in extra)
        shown = ', '.join(f'{n:.0f}' if years else f'{n:,.10g}' for n in sorted(extra))
        issues.append(f'new or altered number: {shown}' + (
            ' (these look like dates; role dates appear in the heading, so leave them out of the text)' if years else
            ' (not found in the cited sources; use the source value or remove it)'))
    for tool in TOOLS:
        pattern = r'(?<![a-z0-9])' + re.escape(tool) + r'(?![a-z0-9])'
        if re.search(pattern, low) and not re.search(pattern, original):
            issues.append('unestablished technology: ' + tool)
    if ('$' in text or re.search(r'\b(dollars|usd)\b', low)) and not re.search(r'\$|usd|dollar', original):
        issues.append('unestablished currency unit')
    if '%' in text and not re.search(r'%|percent', original):
        issues.append('unestablished percentage')
    if re.search(r'\b(created|published|authored|maintained)\b.{0,45}\b(npm|nuget|enterprise packages?)\b', low) and not re.search(r'\b(created|published|authored|maintained)\b.{0,45}\b(npm|nuget|enterprise packages?)\b', original):
        issues.append('dependency use upgraded to package authorship')
    if re.search(r'database administrat|\bdba\b', low) and not re.search(r'database administrat|\bdba\b', original):
        issues.append('unestablished database administration')
    for phrase in ('sole', 'enterprise-wide', 'entire platform', 'organization-wide'):
        if re.search(r'\b' + re.escape(phrase) + r'\b', low) and phrase not in original:
            issues.append('unestablished architecture/ownership scope')
    metric_pairs = []
    def collect_units(value):
        if isinstance(value, dict):
            if value.get('unit'):
                for key in ('value','low','high'):
                    if isinstance(value.get(key), (int,float)):
                        metric_pairs.append((float(value[key]), str(value['unit']).lower()))
            for item in value.values():
                collect_units(item)
        elif isinstance(value, list):
            for item in value:
                collect_units(item)
    for e in linked:
        collect_units(e.fact_details)
        collect_units([m.model_dump() for m in e.metrics])
    unit_patterns = {'currency': r'\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)([kKmM]?)',
                     'credits': r'([0-9][0-9,]*(?:\.[0-9]+)?)([kKmM]?)\s+credits?\b',
                     'hours': r'([0-9][0-9,]*(?:\.[0-9]+)?)([kKmM]?)\s+hours?\b'}
    for unit, pattern in unit_patterns.items():
        for raw, suffix in re.findall(pattern, text, re.I):
            amount = float(raw.replace(',', '')) * {'':1,'k':1000,'m':1000000}[suffix.lower()]
            supports_pair = any(value == amount and (('usd' in known or 'dollar' in known) if unit == 'currency' else unit[:-1] in known) for value, known in metric_pairs)
            if not supports_pair and not any(numbers(match[0] + match[1]) == {amount} for match in re.findall(pattern, source, re.I)):
                issues.append('number/unit pairing not supported: ' + unit)
    for e in linked:
        for tech in e.technologies:
            if tech.context != 'professional' and tech.name.lower() in low and re.search(r'\b(production|professional|enterprise|administered|operated|deployed)\b', low) and not re.search(r'\b(training|academic|portfolio|coursework)\b', low):
                issues.append('nonprofessional technology exposure upgraded')
        metrics = [m.model_dump() for m in e.metrics]
        if e.fact_details.get('metric'):
            metrics.append(e.fact_details['metric'])
        for m in metrics:
            meaning = m.get('meaning', 'unspecified')
            interpretation = str(e.fact_details.get('comparison', {}).get('interpretation', '')).lower()
            if meaning == 'unspecified' and 'reduction' in interpretation:
                meaning = 'reduction'
            if meaning == 'reduction' and m['value'] in numbers(text):
                value = re.escape(f"{m['value']:g}")
                if (not re.search(r'\b(reduc\w*|decreas\w*|lower\w*|fewer|sav\w*|drop\w*)\b', low)
                    or re.search(r'\b(?:to|at)\s+(?:approximately\s+|about\s+|roughly\s+)?' + value + r'\b', low)):
                    issues.append('reduction presented as a usage level')
            relevant = m['value'] in numbers(text) or bool(re.search(r'\b(saved|savings|reduced|reduction|improved)\b', low))
            if not relevant:
                continue
            if m.get('qualifier') in ('estimated','approximately') and not qualified_number(text, m['value'], 'estimated|approximately|approx|about|roughly'):
                issues.append('lost estimated/approximate qualifier')
            if m.get('qualifier') == 'expected' and not qualified_number(text, m['value'], 'expected'):
                issues.append('expected outcome presented as realized')
    for verb in OWNERSHIP_VERBS:
        verb_pattern = r'\b' + verb + (r'\b(?!\s+to\b)' if verb == 'led' else r'\b')
        if re.search(verb_pattern, low) and not re.search(OWNERSHIP_VERBS[verb], original):
            if verb != 'owned' or not any(e.ownership == 'owned' for e in linked):
                issues.append(f"unestablished ownership verb: {verb} (the cited sources do not say you {verb} this; "
                              "use the source's own verb, such as built, designed or contributed to)")
    if re.search(r'\b(doctor|doctorate|doctoral|phd)\b', low) and re.search(r'in progress|dissertation phase|enrolled', original) and not re.search(r'in progress|dissertation|enrolled|student|research', low):
        issues.append('in-progress education qualifier omitted')
    if re.search(r'\b(managed|led|supervised)\s+(a\s+)?(team|staff|employees)|direct reports', low):
        # Peer training and a "tech lead type role" do not establish people management.
        if not re.search(r'\b(managed|supervised)\s+(a\s+)?(team|staff|employees)|direct reports', original):
            issues.append('unestablished people-management scope')
    if re.search(r'completed.*(doctor|phd)|earned.*(doctor|phd)|doctoral candidate', low) and re.search(r'in progress|dissertation phase|enrolled', original):
        issues.append('in-progress education upgraded')
    return issues


def accepted_assessments(packet, career, raw_assessments):
    index = {e.id:e for e in career.evidence}
    claims = {c.id:c for c in packet.resume + packet.cover_letter}
    accepted, rejected = set(), {}
    for raw in raw_assessments:
        assessment = ClaimAssessment.model_validate(raw)
        claim = claims.get(assessment.claim_id)
        if not claim:
            raise ValueError('Auditor assessed an unknown claim')
        if assessment.claim_id in accepted or assessment.claim_id in rejected:
            raise ValueError('Duplicate claim support assessment')
        if set(assessment.evidence_ids) != set(claim.evidence_ids):
            raise ValueError('Support assessment does not match cited evidence')
        linked = [index[i] for i in claim.evidence_ids if i in index]
        reasons = []
        if len(linked) != len(claim.evidence_ids) or not all(e.eligible for e in linked):
            reasons.append('missing or uncertain evidence')
        checked = ('wording_supported','metrics_consistent','technology_consistent','scope_consistent','dates_titles_consistent')
        failed = [label for key, label in zip(checked, ('wording', 'metrics', 'technology', 'scope', 'dates or titles'))
                  if not getattr(assessment, key)]
        if failed:
            reasons.append('the fact-check reviewer found the ' + ', '.join(failed) + ' not supported by the cited sources')
        quoted = set()
        for quote in assessment.quotes:
            if quote.evidence_id not in claim.evidence_ids or quote.evidence_id not in index:
                raise ValueError('Support quote references uncited evidence')
            if quote.text not in source_text(index[quote.evidence_id]):
                reasons.append('supporting quote is not present in the source')
            else:
                quoted.add(quote.evidence_id)
        if quoted != set(claim.evidence_ids):
            reasons.append('not every cited record has an exact supporting quote')
        reasons += deterministic_objections(claim.text, linked)
        if reasons:
            rejected[claim.id] = sorted(set(reasons))
        else:
            accepted.add(claim.id)
    return accepted,rejected
