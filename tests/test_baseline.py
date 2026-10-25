from pathlib import Path
from docx import Document
from career_pipeline.models import Career, Employment, Packet, Settings
from career_pipeline.baseline import employment_baseline
from career_pipeline.export import preview, export
from career_pipeline.pipeline import run
from career_pipeline.store import Store


def career():
    c = Career.model_validate_json(Path('fixtures/career.json').read_text(encoding='utf-8'))
    c.employments = [Employment(id='older', employer='Older Example Co', official_title='Analyst', start='2020-01', end='2021-12'),
                     Employment(id='newer', employer='Newer Example Co', official_title='Analyst III', start='2024-07',
                                resume_display_title='Data Engineer', resume_display_title_approved=True)]
    c.evidence[0].employment_ids = ['older']
    c.evidence[1].employment_ids = ['newer']
    return c


def test_headers_exist_without_any_generated_claims_and_keep_approved_titles():
    c = career()
    text, _ = preview(Packet(resume=[], cover_letter=[]), c)
    assert 'Data Engineer — Newer Example Co' in text
    assert 'Jul 2024 – Present' in text
    assert 'Analyst — Older Example Co' in text
    assert text.index('Newer Example Co') < text.index('Older Example Co')
    assert c.employments[1].official_title == 'Analyst III'


def test_generated_bullet_order_cannot_reorder_jobs_or_change_the_baseline():
    c = career()
    packet = Packet(resume=[dict(id=e.id, text=e.supported_wording[0], evidence_ids=[e.id]) for e in c.evidence], cover_letter=[])
    before = employment_baseline(c)
    a, _ = preview(packet, c)
    packet.resume.reverse()
    b, _ = preview(packet, c)
    assert [line for line in a.splitlines() if line.startswith('### ')] == [line for line in b.splitlines() if line.startswith('### ')]
    assert employment_baseline(c) == before


def test_shared_work_retains_explicit_scope_under_each_saved_job():
    c = career()
    c.evidence[0].employment_ids = ['older', 'newer']
    text = c.evidence[0].supported_wording[0]
    rendered, _ = preview(Packet(resume=[dict(id='shared', text=text, evidence_ids=[c.evidence[0].id])], cover_letter=[]), c)
    assert rendered.count(text) == 2
    assert rendered.count('Shared across ') == 2
    assert rendered.index('Shared across ') < rendered.index(text)


def test_history_without_source_bullets_stops_before_model_generation(tmp_path):
    import pytest
    c = career()
    c.employments.append(Employment(id='no-evidence', employer='Earliest Example Co', official_title='Assistant', start='2018-01', end='2019-12'))
    with Store(str(tmp_path/'runs.sqlite')) as store:
        with pytest.raises(ValueError, match='source bullets'):
            run('Required: Python data ingestion.', c, store, Settings(include_cover_letter=False))
        m = store.history()[0]
        assert m['failure']['code'] == 'missing_source_bullets'
        assert not m['versions']
        assert not any(stage['name']=='generate' for stage in m['stages'])
