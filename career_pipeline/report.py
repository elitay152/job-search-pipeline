"""Readable run inspection: generated versions and reviewer objections, not hidden manual drafts."""
import difflib
from .models import Packet, Requirement
from .workbench import fit_report
from .export import preview

def review_report(manifest, career):
    lines = [f"# Pipeline run {manifest['id']}", f"Status: {manifest['status']}",
        f"Generator: {manifest['settings']['generator']} / Reviewer: {manifest['settings']['reviewer']}",
        f"Stopping reason: {manifest.get('stopping_reason', 'running')}"]
    if manifest.get('failure'):
        lines += [f"Stopped at {manifest['failure']['stage']}: {manifest['failure']['message']}"]
    if manifest['settings']['reviewer'] == 'mock':
        lines += ['**MOCK — deterministic software validation, not a live adversarial model review.**']
    packet = Packet.model_validate(manifest['versions'][-1]['packet']) if manifest['versions'] else None
    requirements = [Requirement.model_validate(q) for q in manifest.get('requirements', [])]
    summary = fit_report(requirements, packet)
    lines += ['## Evidence coverage',
        f"Supported requirements represented: {summary['covered']} / {summary['supported']}.",
        f"Required items with evidence: {summary['required_supported']} / {summary['required_total']}.",
        f"Direct: {summary['direct']}; transferable: {summary['transferable']}; gaps: {summary['gaps']}; clarification needed: {summary['clarifications']}.",
        'Lexical matching and cited evidence are not proof of semantic coverage. This is not an ATS score or a hiring prediction.']
    for requirement in requirements:
        lines += [f"- {requirement.priority.title()} / {requirement.classification.replace('_', ' ')}: {requirement.excerpt}"]
    if manifest.get('follow_up_answers'):
        lines += ['## Your follow-up answers']
        lines += [f"- {value['requirement_id']}: {value['answer']}" for value in manifest['follow_up_answers'].values()]
    for version in manifest['versions']:
        lines += [f"## Version {version['number']}"]
        quality_status = version.get('content_quality_status', 'not_recorded')
        lines += ['Writing-quality heuristics: ' + {'assessed': 'assessed (presentation warnings, not factual certification)',
            'disabled': 'disabled by configuration', 'not_assessed_practice': 'not assessed for practice output',
            'not_recorded': 'not recorded for this older run'}.get(quality_status, quality_status)]
        for role, receipt in version.get('reviews', {}).items():
            lines += [f"{role}: {receipt['status']} ({receipt['provider']})"]
            for attempt in receipt.get('attempts', []):
                if attempt['status'] == 'rejected':
                    lines += [f"Response contract rejected: {attempt['error']} (retained in run manifest)."]
        for f in version['findings']:
            target = f.get('claim_id') or f.get('section') or f.get('requirement_id') or 'packet'
            lines += [f"- [{f['severity']}] {f['role']} / {target}: {f['message']}"]
    if len(manifest['versions']) > 1:
        before = '\n'.join(preview(Packet.model_validate(manifest['versions'][0]['packet']), career)).splitlines()
        after = '\n'.join(preview(Packet.model_validate(manifest['versions'][-1]['packet']), career)).splitlines()
        lines += ['## Revision diff', '```diff', *difflib.unified_diff(before, after, fromfile='initial', tofile='latest'), '```']
    if manifest['versions']:
        resume, letter = preview(Packet.model_validate(manifest['versions'][-1]['packet']), career)
        lines += ['## Latest resume — review draft', resume, '## Latest cover letter — review draft', letter]
    return '\n\n'.join(lines)
