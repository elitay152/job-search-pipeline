"""Convert private, scoped confirmations into generation schemas without inventing dates.

Raw source-only records remain uncertain. Proposed prose is not falsely labeled user-approved.
No personal names, employers, academic samples or source documents are bundled in this module.
"""
import json
import re
from pathlib import Path
from .models import Career, Evidence, Employment, Source, Technology, Metric
from .store import digest

CATALOG = [
    ('SQL Server', r'\bSQL Server\b', 'Data platforms'),
    ('Snowflake', r'\bSnowflake\b', 'Data platforms'),
    ('Databricks', r'\bDatabricks\b', 'Data platforms'),
    ('PySpark', r'\bPySpark\b', 'Languages & processing'),
    ('Python', r'\bPython\b', 'Languages & processing'),
    ('SQL', r'\bSQL\b', 'Languages & processing'),
    ('pandas', r'\bpandas\b', 'Languages & processing'),
    ('dbt', r'\bdbt\b', 'Modeling & quality'),
    ('Delta tables', r'\bDelta tables\b', 'Modeling & quality'),
    ('Medallion architecture', r'\bmedallion\b', 'Modeling & quality'),
    ('Datadog', r'\bDatadog\b', 'Monitoring'),
    ('Azure DevOps', r'\bAzure DevOps\b', 'Delivery'),
    ('Azure file shares', r'\bAzure file ?share\b', 'Data platforms'),
    ('GitHub CI/CD', r'\bGitHub CI/CD\b', 'Delivery'),
    ('Kubernetes deployment', r'\bKubernetes\b', 'Delivery'),
    ('npm dependencies', r'\bnpm\b', 'Development tools'),
    ('Power BI', r'\bPower BI\b', 'Visualization'),
    ('R', r'\bR\b', 'Languages & processing'),
    ('Azure Data Factory', r'\bAzure Data Factory\b', 'Data platforms'),
]


def technologies(text, kind):
    result = []
    for name, pattern, category in CATALOG:
        flags = 0 if name == 'R' else re.I
        if not re.search(pattern, text, flags):
            continue
        context = 'professional'
        if name == 'Azure Data Factory' and 'training' in text.lower():
            context = 'training'
        elif name == 'R' and re.search(r'academic|school', text, re.I):
            context = 'academic'
        elif name == 'Power BI' and re.search(r'portfolio|github', text, re.I):
            context = 'portfolio'
        elif kind == 'project':
            context = 'portfolio'
        result.append(Technology(name=name, usage=text, context=context, category=category))
    return result


def statements_from_facts(facts):
    """Only canonical fact fields, never unapproved candidate prose, become support text."""
    result = []
    actions = facts.get('personally_performed', []) + facts.get('specific_contributions', [])
    for action in actions:
        context = facts.get('technology')
        result.append(f'{context}: {action}.' if context else action.rstrip('.') + '.')
    if facts.get('metric'):
        metric = facts['metric']
        description = facts.get('scope') or metric.get('basis') or 'Recorded measure'
        meaning = metric.get('meaning', 'unspecified')
        if meaning == 'unspecified' and 'reduction' in str(facts.get('comparison', {}).get('interpretation', '')).lower():
            meaning = 'reduction'
        if meaning in ('reduction', 'increase'):
            description = meaning.title() + ' — ' + description
        qualifier = metric.get('qualifier', '')
        result.append(f"{description}: {qualifier} {metric['value']:g} {metric['unit']}.".replace(':  ', ': '))
    if facts.get('activity'):
        contexts = '; '.join(facts.get('contexts', []))
        result.append(f"{facts['activity']}" + (f' ({contexts}).' if contexts else '.'))
    if facts.get('technology') and not actions:
        result.append(f"Used {facts['technology']} in {facts.get('context', 'the stated context')}.")
    for name in ('Azure Data Factory', 'Azure DevOps'):
        if isinstance(facts.get(name), dict):
            result.append(f"{name}: {facts[name]['setting']}.")
    for degree in facts.get('degrees', []):
        text = degree['degree'] + ' | ' + degree['institution']
        if degree.get('completed_month'):
            text += ' | ' + degree['completed_month']
        elif degree.get('status'):
            text += ' | ' + degree['status']
        result.append(text)
    return list(dict.fromkeys(result))


def import_intake(directory, output):
    root = Path(directory)
    draft = json.loads((root/'career.evidence-draft.json').read_text(encoding='utf-8'))
    ledger = json.loads((root/'user-confirmations.json').read_text(encoding='utf-8'))
    records = {r['id']: r for r in draft['records']}
    roles = {}
    by_employer = {}
    # Keep user-approved official/display title distinctions. Exact source metadata is retained
    # in the conversion report for human packet review, never inferred from a target role.
    for r in records.values():
        meta = r.get('employment_as_reported') or {}
        title = meta.get('official_title') or meta.get('title_as_written')
        if not title or not meta.get('start_month') or not meta.get('end_month'):
            continue
        if meta.get('month_range_status') != 'user_confirmed':
            continue
        employer = meta.get('employer_as_written')
        if not employer:
            continue
        ident = 'job-' + digest([employer, title, meta['start_month'], meta['end_month']])[:12]
        role = Employment(id=ident, employer=employer, official_title=title,
            start=meta['start_month'], end=meta['end_month'],
            resume_display_title=meta.get('resume_display_title'),
            resume_display_title_approved=meta.get('resume_display_title_status') == 'user_approved_descriptive_label')
        roles[ident] = role
        by_employer.setdefault(employer, set()).add(ident)
    evidence = []
    imported = []
    pending = []
    for confirmation in ledger['confirmations']:
        if confirmation.get('status') != 'user_confirmed_for_listed_facts_only':
            continue
        targets = [records[i] for i in confirmation.get('record_ids', []) if i in records]
        facts = confirmation.get('confirmed_facts', {})
        candidates = statements_from_facts(facts)
        employers = {m.get('employer_as_written') for r in targets if (m := r.get('employment_as_reported'))}
        employers.discard(None)
        employer = next(iter(employers)) if len(employers) == 1 else ''
        if 'degrees' in facts:
            kind = 'education'
        elif targets and all(r['record_type'] == 'independent_project' for r in targets):
            kind = 'project'
        elif targets and all(r['record_type'] in ('academic_projects', 'training', 'mixed_employment_and_projects') for r in targets):
            kind = 'skill'
        else:
            kind = 'experience'
        # A tool-context confirmation is a skill, not a new employment achievement.
        if set(facts).intersection(('Azure Data Factory', 'Azure DevOps')):
            kind = 'skill'
        for number, text in enumerate(candidates):
            if not text or not text.strip():
                continue
            ident = 'fact-' + digest([confirmation['id'], number])[:16]
            source = Source(reference=f'{root}/user-confirmations.json#{confirmation["id"]}', status='user_confirmed', excerpt=confirmation.get('user_statement'))
            metric = facts.get('metric', {})
            metrics = [Metric.model_validate(metric)] if metric.get('qualifier') in ('realized', 'estimated', 'expected') else []
            # A confirmation can cover multiple degrees. Each evidence record must describe
            # only its matching degree, rather than inheriting the first target's label
            # and every degree's metadata (which could falsely support cross-degree claims).
            degree = next((d for d in facts.get('degrees', [])
                           if text in statements_from_facts({'degrees': [d]})), None)
            record_facts = dict(facts, degrees=[degree]) if degree else facts
            project = degree['degree'] if degree else targets[0]['topic'] if targets else confirmation['id']
            evidence.append(Evidence(id=ident, kind=kind, employer=employer,
                employment_ids=sorted(by_employer.get(employer, [])) if kind == 'experience' else [],
                project=project,
                actions=facts.get('personally_performed', [text]), ownership='contributed',
                technologies=technologies(text, kind), metrics=metrics, sources=[source],
                confirmed_statements=[text], fact_details=record_facts, prohibited_inferences=confirmation.get('prohibited_inferences', []),
                tags=[t.name for t in technologies(text, kind)]))
            imported.append({'id': ident, 'confirmation_id': confirmation['id'], 'kind': kind,
                             'wording_basis': 'deterministically normalized confirmed_facts fields; unapproved candidate_wording is ignored'})
    # Retain bibliographic/source-only records explicitly as uncertain, never silently verify
    # them because the user approved a style sample or asked for a section to appear.
    for record in records.values():
        if record.get('record_type') != 'publication':
            continue
        variants = record.get('candidate_wording_variants', [])
        if not variants:
            continue
        text = variants[0]['text']
        evidence.append(Evidence(id=record['id'], kind='publication', project=record['topic'],
            actions=[], ownership='contributed', technologies=[],
            sources=[Source(reference=f'{root}/career.evidence-draft.json#{record["id"]}', status='uncertain')],
            confirmed_statements=[text]))
        pending.append({'id': record['id'], 'reason': 'Citation is source-backed but its complete factual wording is not yet confirmed. It remains visible for clarification, not fabricated or silently dropped.'})
    result = Career(display_name=draft['display_name'], contact=draft.get('contact', []),
                    employments=list(roles.values()), presentation=draft.get('presentation', {}), evidence=evidence)
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise ValueError('Refusing to overwrite an existing evidence snapshot; choose a new version')
    dest.write_text(result.model_dump_json(indent=2), encoding='utf-8')
    dest.with_suffix('.import-report.json').write_text(json.dumps({'converter_version': 'facts-only-v2', 'source_hash': digest(ledger),
        'career_hash': digest(result.model_dump(mode='json')), 'imported': imported, 'pending': pending,
        'metadata_note': 'Only confirmed month ranges are imported. Display titles require explicit approval; original titles and source metadata remain available for user packet review.'}, indent=2), encoding='utf-8')
    return result
