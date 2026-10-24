"""Exercise user actions against an isolated local workspace; never call live providers."""
import shutil
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from career_pipeline.models import Career

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    shutil.copytree(ROOT / 'fixtures', tmp_path / 'fixtures')
    shutil.copytree(ROOT / 'writing_style', tmp_path / 'writing_style')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('CAREER_DB', raising=False)
    return tmp_path


def field(app, kind, label):
    return next(element for element in getattr(app, kind) if element.label == label)


def test_first_use_and_confirmed_evidence_form(workspace):
    app = AppTest.from_file(str(ROOT / 'career_pipeline/ui.py')).run()
    assert not app.exception
    assert field(app, 'button', 'Create my draft').disabled
    assert not any(e.label.startswith('Career evidence JSON') for e in app.text_area)
    field(app, 'text_input', 'Name').set_value('Morgan Example')
    field(app, 'button', 'Save contact details').click().run()
    field(app, 'text_input', 'Project or accomplishment').set_value('Warehouse ingestion')
    field(app, 'text_area', 'Factual statements — one per line').set_value('Built Python ingestion with duplicate checks.')
    field(app, 'text_area', 'Actions you personally performed — one per line').set_value('Built ingestion.')
    field(app, 'button', 'Save evidence').click().run()
    assert not app.exception
    career = Career.model_validate_json((workspace / 'local/career.json').read_text())
    assert career.display_name == 'Morgan Example'
    assert not career.evidence[0].eligible
    assert field(app, 'button', 'Create my draft').disabled
    field(app, 'selectbox', 'Add or edit evidence').select(career.evidence[0].id).run()
    field(app, 'checkbox', 'I reviewed these facts and their sources and confirm they are accurate').check()
    field(app, 'button', 'Save evidence').click().run()
    assert not app.exception
    confirmed = Career.model_validate_json((workspace / 'local/career.json').read_text())
    assert confirmed.evidence[0].eligible
    assert confirmed.evidence[0].id == career.evidence[0].id


def test_mock_application_previews_and_readable_reviews(workspace):
    app = AppTest.from_file(str(ROOT / 'career_pipeline/ui.py')).run()
    field(app, 'button', 'Load synthetic example').click().run()
    field(app, 'text_area', 'Paste the job description').set_value((workspace / 'fixtures/job.txt').read_text()).run()
    assert not field(app, 'button', 'Create my draft').disabled
    field(app, 'button', 'Create my draft').click().run(timeout=20)
    assert not app.exception
    assert field(app, 'checkbox', 'I reviewed the wording, supporting evidence, dates and unresolved gaps.')
    assert any('Synthetic Analytics' in element.value for element in app.markdown)
    assert any('Relevance & presentation' in element.value for element in app.warning)
    assert field(app, 'button', 'Approve this application').disabled  # acknowledgment is required
    field(app, 'button', 'Prepare documents').click().run()
    assert not app.exception
    assert list((workspace / 'artifacts').rglob('*.docx'))


def test_employment_form_validates_dates(workspace):
    app = AppTest.from_file(str(ROOT / 'career_pipeline/ui.py')).run()
    field(app, 'text_input', 'Employer').set_value('Example Co')
    field(app, 'text_input', 'Official job title').set_value('Analyst')
    field(app, 'text_input', 'Start (YYYY-MM)').set_value('2025-03')
    field(app, 'text_input', 'End (blank if current)').set_value('2024-03')
    field(app, 'button', 'Save role').click().run()
    assert not app.exception
    assert any('end precedes start' in error.value for error in app.error)
    field(app, 'text_input', 'End (blank if current)').set_value('2026-03')
    field(app, 'button', 'Save role').click().run()
    career = Career.model_validate_json((workspace / 'local/career.json').read_text())
    assert career.employments[0].start == '2025-03'


def test_gap_answers_update_library_and_survive_new_session(workspace):
    app = AppTest.from_file(str(ROOT / 'career_pipeline/ui.py')).run()
    field(app, 'button', 'Load synthetic example').click().run()
    field(app, 'text_area', 'Paste the job description').set_value('Required: Kubernetes production administration.').run()
    answer = next(e for e in app.text_area if e.key and e.key.startswith('answer_'))
    answer.set_value('Configured Kubernetes production administration for a synthetic test environment.')
    next(e for e in app.text_input if e.key and e.key.startswith('tool_')).set_value('Kubernetes')
    next(e for e in app.text_input if e.key and e.key.startswith('usage_')).set_value('Production administration')
    next(e for e in app.checkbox if e.key and e.key.startswith('gap_confirm_')).check()
    field(app, 'button', 'Save answer').click().run()
    assert not app.exception
    saved = Career.model_validate_json((workspace / 'local/career.json').read_text())
    assert any(e.id.startswith('answer-') and e.eligible for e in saved.evidence)
    fresh = AppTest.from_file(str(ROOT / 'career_pipeline/ui.py')).run()
    assert not fresh.exception
    assert any('3' == metric.value for metric in fresh.metric if metric.label == 'Confirmed evidence')


def test_corrupt_library_has_recovery_without_overwrite(workspace):
    target = workspace / 'local/career.json'
    target.parent.mkdir()
    target.write_text('not valid data')
    app = AppTest.from_file(str(ROOT / 'career_pipeline/ui.py')).run()
    assert not app.exception
    assert any('could not be read' in message.value for message in app.warning)
    assert target.read_text() == 'not valid data'


def test_approval_replaces_prepared_draft_downloads_with_final_files(workspace):
    from docx import Document
    app=AppTest.from_file(str(ROOT/'career_pipeline/ui.py')).run()
    field(app,'button','Load synthetic example').click().run()
    field(app,'text_area','Paste the job description').set_value((workspace/'fixtures/job.txt').read_text()).run()
    field(app,'button','Create my draft').click().run(timeout=20)
    field(app,'button','Prepare documents').click().run()
    assert all('/draft/' in p for p in app.session_state['downloads'])
    field(app,'checkbox','I reviewed the wording, supporting evidence, dates and unresolved gaps.').check().run()
    field(app,'button','Approve this application').click().run()
    assert not app.exception
    assert all('/final/' in p for p in app.session_state['downloads'])
    resume=next(Path(p) for p in app.session_state['downloads'] if p.endswith('resume.docx'))
    assert not any('DRAFT' in p.text for p in Document(resume).paragraphs)
    assert any(s.value=='Approved' for s in app.subheader)
