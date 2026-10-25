from pathlib import Path
import json
import pytest
from docx import Document
from career_pipeline.models import Career
from career_pipeline.pipeline import run
from career_pipeline.store import Store
from career_pipeline.export import export, approve, XML_INVALID


def test_draft_export_handles_controls_and_audit_preserves_original(tmp_path):
    career=Career.model_validate_json(Path('fixtures/career.json').read_text())
    career.contact=['Synthetic\x00 contact\x0b with\ud800 bad\ufffe characters']
    store=Store(str(tmp_path/'runs.sqlite'))
    m=run(Path('fixtures/job.txt').read_text(),career,store)
    with pytest.raises(ValueError,match='control characters'):
        approve(store,m['id'],career,True)
    assert not store.get(m['id'])['approved']
    paths=export(store,m['id'],career,tmp_path/'exports',draft=True)
    doc=Document(next(p for p in paths if p.name=='resume.docx'))
    rendered='\n'.join(p.text for p in doc.paragraphs)
    assert '\ufffd' in rendered and not XML_INVALID.search(rendered)
    assert store.career_snapshot(m['id']).contact==career.contact
    saved=json.loads(next(p for p in paths if p.name=='audit.json').read_text())
    assert saved['render_warnings'][0]['count']==4
    assert saved['render_warnings'][0]['codepoints']==['U+0000','U+000B','U+D800','U+FFFE']


def test_normal_unicode_tabs_and_line_breaks_are_preserved():
    text='Résumé — SQL\tPython\nData\rEngineering 😀'
    assert XML_INVALID.sub('\ufffd',text)==text


def test_invalid_generated_character_is_sent_to_revision_even_if_grounded():
    from career_pipeline.models import Packet
    from career_pipeline.review import audit
    career=Career.model_validate_json(Path('fixtures/career.json').read_text())
    packet=Packet(resume=[{'id':'r1','text':'Built\x19 pipelines.','evidence_ids':['ev-pipeline']}],
                  cover_letter=[{'id':'c1','text':'Built pipelines.','evidence_ids':['ev-pipeline']}])
    findings=audit(packet,career,grounded_claims={'r1','c1'})
    assert any(f.code=='invalid_document_character' and f.claim_id=='r1' for f in findings)
