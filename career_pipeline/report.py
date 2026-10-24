"""Readable run inspection: generated versions and reviewer objections, not hidden manual drafts."""
import difflib
import json
from .models import Packet
from .export import preview

def review_report(manifest, career):
    lines = [f"# Pipeline run {manifest['id']}", f"Status: {manifest['status']}",
        f"Generator: {manifest['settings']['generator']} / Reviewer: {manifest['settings']['reviewer']}",
        f"Stopping reason: {manifest.get('stopping_reason', 'running')}"]
    if manifest['settings']['reviewer'] == 'mock':
        lines += ['**MOCK — deterministic software validation, not a live adversarial model review.**']
    for version in manifest['versions']:
        lines += [f"## Version {version['number']}"]
        for role, receipt in version.get('reviews', {}).items():
            lines += [f"{role}: {receipt['status']} ({receipt['provider']})"]
            for attempt in receipt.get('attempts', []):
                if attempt['status'] == 'rejected':
                    lines += [f"Response contract rejected: {attempt['error']} (retained in run manifest)."]
        for f in version['findings']:
            target = f.get('claim_id') or f.get('section') or f.get('requirement_id') or 'packet'
            lines += [f"- [{f['severity']}] {f['role']} / {target}: {f['message']}"]
    if len(manifest['versions']) > 1:
        before = json.dumps(manifest['versions'][0]['packet'], indent=2).splitlines()
        after = json.dumps(manifest['versions'][-1]['packet'], indent=2).splitlines()
        lines += ['## Revision diff', '```diff', *difflib.unified_diff(before, after, fromfile='initial', tofile='latest'), '```']
    if manifest['versions']:
        resume, letter = preview(Packet.model_validate(manifest['versions'][-1]['packet']), career)
        lines += ['## Latest resume — review draft', resume, '## Latest cover letter — review draft', letter]
    return '\n\n'.join(lines)
