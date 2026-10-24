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


def numbers(text):
    clean = text.lower().replace(',', '')
    # Compare common K/M renderings without allowing newly annualized/multiplied outcomes.
    return {float(n) * {'k':1000, 'm':1000000, '':1}[unit] for n,unit in
            re.findall(r'(?<![\w])([0-9]+(?:\.[0-9]+)?)\s*([km]?)(?![\w])', clean)}


def source_text(e):
    return '\n'.join(e.supported_wording + [s.excerpt for s in e.sources if s.excerpt] +
                     [json.dumps(e.fact_details, ensure_ascii=False), json.dumps([m.model_dump() for m in e.metrics]),
                      ' '.join(t.name + ' ' + t.usage for t in e.technologies)])


def deterministic_objections(text, linked):
    source = '\n'.join(source_text(e) for e in linked)
    low, original = text.lower(), source.lower()
    issues = []
    if not numbers(text) <= numbers(source):
        issues.append('new or altered number')
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
            relevant = m['value'] in numbers(text) or bool(re.search(r'\b(saved|savings|reduced|reduction|improved)\b', low))
            if not relevant:
                continue
            if m.get('qualifier') in ('estimated','approximately') and not re.search(r'\b(estimated|approximately|about|roughly)\b', low):
                issues.append('lost estimated/approximate qualifier')
            if m.get('qualifier') == 'expected' and 'expected' not in low:
                issues.append('expected outcome presented as realized')
    for verb in ('owned','led','managed','supervised','directed','architected'):
        if re.search(r'\b' + verb + r'\b', low) and not re.search(r'\b' + verb + r'\b', original):
            if verb != 'owned' or not any(e.ownership == 'owned' for e in linked):
                issues.append('unestablished ownership verb: ' + verb)
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
        if not all(getattr(assessment,key) for key in checked):
            reasons.append('live auditor found an unsupported factual element')
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
