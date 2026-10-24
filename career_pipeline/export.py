import json
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt
from .models import Career, Packet
from .pipeline import audit
from .store import digest, now

def resume_title(evidence):
    return (evidence.resume_display_title
            if evidence.resume_display_title and evidence.resume_display_title_approved
            else evidence.official_title)


def resume_date(value):
    return value.strftime('%b %Y') if value else 'Present'


def preview(packet, career):
    index = {e.id: e for e in career.evidence}
    resume = [f'# {career.display_name}', '## Professional Experience']
    groups = {}
    for claim in packet.resume:
        e = index.get(claim.evidence_ids[0])
        key = (e.employer, e.official_title, resume_title(e), e.start, e.end) if e else ('unknown',)
        if key not in groups:
            groups[key] = (e, [])
        groups[key][1].append(claim)
    for e, claims in groups.values():
        if e:
            resume += [f'### {resume_title(e)} — {e.employer}',
                       f'{resume_date(e.start)} – {resume_date(e.end)}']
        resume += [f'- {claim.text}' for claim in claims]
    letter = [f'# {career.display_name}', 'Dear Hiring Team,', *[c.text for c in packet.cover_letter], 'Thank you for your consideration.']
    return '\n\n'.join(resume), '\n\n'.join(letter)


def approve(store, run_id, career, acknowledged=False):
    if not acknowledged:
        raise ValueError('Explicit user review acknowledgement required')
    m = store.get(run_id)
    if digest(career.model_dump(mode='json')) != m['evidence_hash']:
        raise ValueError('Evidence snapshot changed; rerun required')
    if not m['versions'] or m['status'] == 'failed':
        raise ValueError('No completed packet')
    packet = Packet.model_validate(m['versions'][-1]['packet'])
    if audit(packet, career):
        raise ValueError('Factual validation blocks approval')
    m.update(status='approved', approved=True, approved_at=now(), approved_packet_hash=digest(packet.model_dump()))
    store.save(m)
    return m

def export(store, run_id, career, directory='artifacts', draft=False):
    m = store.get(run_id)
    packet = Packet.model_validate(m['versions'][-1]['packet'])
    if digest(career.model_dump(mode='json')) != m['evidence_hash']:
        raise ValueError('Evidence snapshot mismatch')
    if not draft and (audit(packet, career) or not m.get('approved') or m.get('approved_packet_hash') != digest(packet.model_dump())):
        raise ValueError('Final export requires passing validation and explicit approval')
    out = Path(directory)/run_id/('draft' if draft else 'final')
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in zip(('resume', 'cover_letter'), preview(packet, career)):
        if draft:
            text = 'DRAFT — NOT APPROVED\n\n' + text
        md = out/f'{name}.md'
        md.write_text(text)
        document = Document()
        section = document.sections[0]
        section.page_width, section.page_height = Inches(8.5), Inches(11)
        section.top_margin = section.bottom_margin = Inches(0.65)
        section.left_margin = section.right_margin = Inches(0.75)
        normal = document.styles['Normal']
        normal.font.name, normal.font.size = 'Calibri', Pt(11)
        normal.paragraph_format.space_after = Pt(6)
        normal.paragraph_format.line_spacing = 1.05
        for level in range(1, 4):
            heading = document.styles[f'Heading {level}']
            heading.font.name = 'Calibri'
            heading.font.size = Pt({1: 18, 2: 13, 3: 11}[level])
            heading.paragraph_format.keep_with_next = True
        for line in text.split('\n\n'):
            if line.startswith('#'):
                document.add_heading(line.lstrip('# '), level=min(len(line)-len(line.lstrip('#')), 3))
            elif line.startswith('- '):
                document.add_paragraph(line[2:], style='List Bullet')
            else:
                document.add_paragraph(line)
        docx = out/f'{name}.docx'
        document.save(docx)
        paths.extend([md, docx])
    for path in paths:
        m['artifacts'].append({'path': str(path), 'sha256': __import__('hashlib').sha256(path.read_bytes()).hexdigest(),
                               'draft': draft, 'created': now()})
    store.save(m)
    report = out/'audit.json'
    report.write_text(json.dumps(m, indent=2))
    return paths + [report]

def export_pdf(*args, **kwargs):
    return {'available': False, 'reason': 'PDF renderer not installed; use editable DOCX or Markdown.'}
