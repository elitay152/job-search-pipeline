import json
from pathlib import Path
import pytest
from career_pipeline.models import Career, Settings, Packet
from career_pipeline.pipeline import run
from career_pipeline.store import Store
from career_pipeline.readiness import check_provider, budget_plan
from career_pipeline.report import review_report
from career_pipeline.workbench import application_label
from career_pipeline.export import export
from career_pipeline.layout import render_layout, inspect_pdf


def test_readiness_never_receives_private_evidence(monkeypatch):
    from career_pipeline.providers import OpenAIProvider
    seen = []
    def complete(self, task, payload, model, max_tokens):
        seen.append(payload)
        assert self.max_attempts == 1 and max_tokens == 1500
        assert payload['career']['display_name'] == 'Synthetic Example'
        return {'result': {'findings': [], 'reviewed_claim_ids': [], 'assessments': []},
                'input_tokens': 50, 'output_tokens': 20}
    monkeypatch.setattr(OpenAIProvider, 'complete', complete)
    monkeypatch.setenv('CAREER_OPENAI_API_KEY', 'synthetic-key')
    monkeypatch.delenv('CAREER_OPENAI_KEY_VARIABLE', raising=False)
    result = check_provider('openai', 'synthetic-model', 'reviewer')
    assert result['status'] == 'passed' and result['input_tokens'] == 50
    assert len(seen) == 1
    assert 'synthetic-key' not in json.dumps(result)


def test_readiness_failure_does_not_expose_sdk_message(monkeypatch):
    from career_pipeline.providers import OpenAIProvider
    monkeypatch.setenv('CAREER_OPENAI_API_KEY', 'synthetic-key')
    monkeypatch.delenv('CAREER_OPENAI_KEY_VARIABLE', raising=False)
    def fail(*args):
        raise RuntimeError('private response text or secret')
    monkeypatch.setattr(OpenAIProvider, 'complete', fail)
    result = check_provider('openai', 'synthetic-model')
    assert result['status'] == 'failed'
    assert 'private response' not in json.dumps(result)
    assert budget_plan(Settings(max_revisions=2))['with_contract_corrections'] == 21


@pytest.fixture
def application(tmp_path):
    career = Career.model_validate_json(Path('fixtures/career.json').read_text())
    store = Store(str(tmp_path/'runs.sqlite'))
    m = run(Path('fixtures/job.txt').read_text(), career, store,
            application={'company': 'Synthetic Co', 'role': 'Data Engineer'})
    paths = export(store, m['id'], career, tmp_path/'exports', draft=True)
    return store, m, paths


def test_named_history_and_report_keep_judgments_separate(application):
    store, m, paths = application
    assert application_label(store.get(m['id'])) == 'Synthetic Co — Data Engineer'
    report = review_report(m, store.career_snapshot(m['id']))
    for phrase in ('JD excerpt:', 'Evidence:', 'Linked passages', 'Judgment sources', 'Human preference'):
        assert phrase in report
    assert application_label({}) == 'Untitled application'


def test_optional_renderer_missing_preserves_editable_files(application, monkeypatch):
    store, m, paths = application
    monkeypatch.setattr('shutil.which', lambda name: None)
    result = render_layout(store, m['id'], paths)
    assert result['status'] == 'unavailable'
    assert all(p.exists() for p in paths)
    assert not store.get(m['id'])['approved']


def test_layout_rejects_modified_source(application, monkeypatch):
    store, m, paths = application
    monkeypatch.setattr('shutil.which', lambda name: 'synthetic-renderer')
    path = next(p for p in paths if p.suffix == '.docx')
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        render_layout(store, m['id'], paths)


def test_pdf_geometry_measures_real_synthetic_pages(tmp_path):
    fitz = pytest.importorskip('fitz')
    pdf = tmp_path/'synthetic.pdf'
    with fitz.open() as document:
        for i in range(2):
            page = document.new_page()
            page.insert_text((50, 50), 'Synthetic heading')
        document.save(pdf)
    result = inspect_pdf(pdf, max_pages=1)
    assert result['page_count'] == 2
    assert any('exceeds' in w for w in result['warnings'])
    assert any('orphaned' in w for w in result['warnings'])


def test_rendered_files_and_human_review_bind_to_exact_artifacts(application, monkeypatch):
    fitz = pytest.importorskip('fitz')
    from career_pipeline.layout import confirm_layout
    store, m, paths = application
    monkeypatch.setattr('shutil.which', lambda name: 'synthetic-renderer')
    def fake_conversion(args, **kwargs):
        directory = Path(args[args.index('--outdir')+1])
        source = Path(args[-1])
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((50, 50), 'Synthetic layout test')
            document.save(directory/(source.stem+'.pdf'))
    monkeypatch.setattr('career_pipeline.layout.subprocess.run', fake_conversion)
    result = render_layout(store, m['id'], paths)
    assert result['status'] == 'rendered' and len(result['documents']) == 2
    assert all(d['inspection']['page_count'] == 1 for d in result['documents'])
    assert confirm_layout(store, m['id'])['human_reviewed']
    assert not store.get(m['id'])['approved']
    Path(result['documents'][0]['pdf']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        confirm_layout(store, m['id'])
