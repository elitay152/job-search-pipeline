"""Readable run inspection: generated versions and reviewer objections, not hidden manual drafts."""
import difflib
from .models import Packet, Requirement
from .workbench import fit_report, requirement_details, application_label
from .export import preview

def review_report(manifest, career):
    lines = [f"# Pipeline run {manifest['id']}", f"Status: {manifest['status']}", application_label(manifest),
        f"Generator: {manifest['settings']['generator']} / Reviewer: {manifest['settings']['reviewer']}",
        f"Stopping reason: {manifest.get('stopping_reason', 'running')}"]
    if manifest.get('failure'):
        lines += [f"Stopped at {manifest['failure']['stage']}: {manifest['failure']['message']}"]
    if manifest['settings']['reviewer'] == 'mock':
        lines += ['**MOCK — deterministic software validation, not a live adversarial model review.**']
    packet = Packet.model_validate(manifest['versions'][-1]['packet']) if manifest['versions'] else None
    requirements = [Requirement.model_validate(q) for q in manifest.get('requirements', [])]
    summary = fit_report(requirements, packet)
    model_matched = manifest.get('requirement_matching', {}).get('method') == 'model'
    def percent(value):
        return 'n/a' if value is None else f'{value}%'
    lines += ['## Evidence coverage',
        f"Requirements covered: {percent(summary['coverage_percent'])} ({summary['covered']} of {summary['total']} addressed by a passage citing matching evidence).",
        f"Required requirements covered: {percent(summary['required_coverage_percent'])} of {summary['required_total']}.",
        f"Direct: {summary['direct']}; transferable: {summary['transferable']}; gaps: {summary['gaps']}; clarification needed: {summary['clarifications']}.",
        ('Requirements were matched to evidence by the generation model, with a stated reason for each.' if model_matched else
         'Requirements were matched by shared words, which can over-count related experience.'),
        'This is not an ATS score or a hiring prediction.']
    for row in requirement_details(requirements, packet, manifest.get('follow_up_answers')):
        lines += [f"### {row['id']} · {row['priority']} · {row['kind']} · {row['classification']}",
            'JD excerpt: ' + row['excerpt'], row['explanation'],
            'Evidence: ' + (', '.join(row['evidence_ids']) or 'none'),
            'Linked passages (not semantic proof): ' + (', '.join(row['passage_ids']) or 'none')]
    lines += ['## Judgment sources', ('Coverage above uses model matching with reasons.' if model_matched else 'Coverage above is deterministic lexical/tag matching.') + ' Reviewer findings below are model judgments in live mode and deterministic checks in practice mode. Human preference and editing effort: not collected by this report.']
    if manifest.get('follow_up_answers'):
        lines += ['## Your follow-up answers']
        lines += [f"- {value['requirement_id']}: {value['answer']}" for value in manifest['follow_up_answers'].values()]
    for version in manifest['versions']:
        lines += [f"## Version {version['number']}"]
        if 'restored_from_version' in version:
            lines += [f"Restored from version {version['restored_from_version']}; later rejected edits remain in this audit."]
        quality_status = version.get('content_quality_status', 'not_recorded')
        lines += ['Writing-quality heuristics: ' + {'assessed': 'assessed (presentation warnings, not factual certification)',
            'disabled': 'disabled by configuration', 'not_assessed_practice': 'not assessed for practice output',
            'not_recorded': 'not recorded for this older run'}.get(quality_status, quality_status)]
        for role, receipt in version.get('reviews', {}).items():
            lines += [f"{role}: {receipt['status']} ({receipt.get('provider', manifest.get('settings', {}).get('reviewer', 'not recorded'))})"]
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
