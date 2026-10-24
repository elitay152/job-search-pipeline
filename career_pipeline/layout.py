"""Optional local PDF rendering with version-bound, heuristic layout inspection."""
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from .models import Packet
from .store import digest, now


def inspect_pdf(path, max_pages=2):
    try:
        import fitz
    except ImportError:
        return {'status': 'unavailable', 'reason': 'Install the layout extra for PDF inspection.'}
    warnings = []
    with fitz.open(path) as document:
        pages = len(document)
        if pages > max_pages:
            warnings.append(f'{pages} pages exceeds your preference of {max_pages}; inspect pagination.')
        for number, page in enumerate(document, 1):
            blocks = [b for b in page.get_text('blocks') if len(b) > 6 and b[6] == 0]
            if not blocks:
                warnings.append(f'Page {number}: no extractable text; inspect visually.')
            for x0, y0, x1, y1, text, *_ in blocks:
                if x0 < 0 or y0 < 0 or x1 > page.rect.width or y1 > page.rect.height:
                    warnings.append(f'Page {number}: text extends beyond page bounds; possible clipping.')
            words = page.get_text('words')
            if len(words) > 650:
                warnings.append(f'Page {number}: dense text ({len(words)} words); inspect readability.')
            # A short final text block may be a stranded heading; human inspection decides.
            if blocks and len(blocks[-1][4].split()) <= 8 and number < pages:
                warnings.append(f'Page {number}: short final block; inspect for an orphaned heading.')
    return {'status': 'inspected', 'page_count': pages, 'warnings': warnings,
            'method': 'Local PDF text geometry heuristics; visual inspection still required.'}


def render_layout(store, run_id, paths, max_resume_pages=2, max_letter_pages=1):
    manifest = store.get(run_id)
    packet_hash = digest(Packet.model_validate(manifest['versions'][-1]['packet']).model_dump())
    report = {'packet_hash': packet_hash, 'version': manifest['versions'][-1]['number'],
              'created': now(), 'documents': [], 'human_reviewed': False}
    executable = shutil.which('libreoffice') or shutil.which('soffice')
    if not executable:
        report.update(status='unavailable', reason='LibreOffice is not installed or not on PATH. DOCX and Markdown remain available.')
    else:
        report['status'] = 'rendered'
        known = {a['path']: a for a in manifest.get('artifacts', [])}
        for path in map(Path, paths):
            if path.suffix != '.docx':
                continue
            if str(path) not in known or known[str(path)].get('packet_hash') != packet_hash or hashlib.sha256(path.read_bytes()).hexdigest() != known[str(path)]['sha256']:
                raise ValueError('Exported document changed; prepare documents again before layout review.')
            item = {'source': str(path), 'source_sha256': known[str(path)]['sha256']}
            try:
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    subprocess.run([executable, '-env:UserInstallation=' + (root/'profile').as_uri(),
                        '--headless', '--convert-to', 'pdf', '--outdir', str(root), str(path.resolve())],
                        check=True, timeout=60, capture_output=True)
                    pdf = root / (path.stem + '.pdf')
                    if not pdf.is_file():
                        raise ValueError('Renderer produced no PDF')
                    result = inspect_pdf(pdf, max_letter_pages if path.stem == 'cover_letter' else max_resume_pages)
                    target = path.with_suffix('.pdf')
                    shutil.copyfile(pdf, target)
                    item.update(pdf=str(target), sha256=hashlib.sha256(target.read_bytes()).hexdigest(), inspection=result)
                    manifest['artifacts'].append({'path': str(target), 'sha256': item['sha256'],
                        'draft': known[str(path)]['draft'], 'packet_hash': packet_hash, 'created': now()})
            except (OSError, ValueError, subprocess.SubprocessError):
                item.update(status='failed', reason='Local rendering or inspection failed. DOCX and Markdown remain available.')
                report['status'] = 'partial_failure'
            report['documents'].append(item)
    manifest['layout_review'] = report
    store.save(manifest)
    return report


def confirm_layout(store, run_id):
    """Record a user's visual review of these exact PDFs, without approving facts."""
    manifest = store.get(run_id)
    report = manifest.get('layout_review', {})
    current_hash = digest(Packet.model_validate(manifest['versions'][-1]['packet']).model_dump())
    if report.get('packet_hash') != current_hash or report.get('status') != 'rendered' or not report.get('documents'):
        raise ValueError('Render the current document version before recording visual review.')
    for item in report['documents']:
        pdf = Path(item['pdf'])
        if pdf.parent.name != ('final' if manifest['approved'] else 'draft') or not pdf.exists() or hashlib.sha256(pdf.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Rendered documents changed or approval status changed; render again.')
    report.update(human_reviewed=True, human_reviewed_at=now())
    store.save(manifest)
    return report
