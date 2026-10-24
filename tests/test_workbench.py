import json
from pathlib import Path
import httpx
import pytest
from career_pipeline.models import Career, Packet, Claim
from career_pipeline.workbench import add_gap_answer, analyze_job, fit_report
from career_pipeline.job_input import load_job_url, public_url


def career():
    return Career(display_name='Synthetic Example', evidence=[])


def test_answer_is_confirmed_once_persisted_and_reused(tmp_path):
    jd = 'Required: Python ingestion and validation.'
    c = career()
    requirement = analyze_job(jd, c)[0]
    target = tmp_path / 'career.json'
    with pytest.raises(ValueError, match='Confirm'):
        add_gap_answer(c, requirement, 'Built Python ingestion and validation.', path=target)
    assert not target.exists()
    c = add_gap_answer(c, requirement, 'Built Python ingestion and validation.', tool='Python', usage='Ingestion and validation', confirmed=True, jd_hash='example', path=target)
    saved = Career.model_validate_json(target.read_text())
    assert saved == c and saved.evidence[0].eligible
    assert analyze_job(jd, saved)[0].classification in ('direct', 'transferable')
    updated = add_gap_answer(saved, requirement, 'Built Python ingestion with validation and error handling.', confirmed=True, jd_hash='example', path=target)
    assert len(updated.evidence) == 1
    packet = Packet(resume=[Claim(id='r1', text=c.evidence[0].supported_wording[0], evidence_ids=[c.evidence[0].id])], cover_letter=[])
    report = fit_report(analyze_job(jd, c), packet)
    assert report['supported'] == report['covered'] == 1
    assert 'probability' not in report


def test_practical_preferences_do_not_become_experience(tmp_path):
    q = analyze_job('Location: hybrid, two days onsite.', career())[0]
    with pytest.raises(ValueError, match='Practical'):
        add_gap_answer(career(), q, 'Yes', confirmed=True, path=tmp_path/'career.json')


def public_dns(monkeypatch):
    monkeypatch.setattr('career_pipeline.job_input.socket.getaddrinfo', lambda *a, **kw: [(2,1,6,'',('93.184.216.34',443))])


def test_public_posting_import_prefers_job_description(monkeypatch):
    public_dns(monkeypatch)
    html = '<nav>Ignore navigation</nav><script type="application/ld+json">' + json.dumps({'@type':'JobPosting','title':'Data Engineer','description':'<p>Required: Python ingestion.</p><p>Preferred: SQL.</p>'}) + '</script>'
    client = httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,headers={'content-type':'text/html'},text=html)))
    text = load_job_url('https://example.com/job', client)
    assert 'Required: Python ingestion.' in text and 'Ignore navigation' not in text
    assert 'Preferred: SQL.' in text


@pytest.mark.parametrize('url',['http://example.com/job','https://user:password@example.com/job','https://example.com:8000/job'])
def test_unsafe_urls_rejected_before_fetch(url):
    with pytest.raises(ValueError):public_url(url)


def test_private_addresses_and_redirects_are_rejected(monkeypatch):
    def resolve(host,*a,**kw):
        return [(2,1,6,'',('127.0.0.1' if host=='internal.example' else '93.184.216.34',443))]
    monkeypatch.setattr('career_pipeline.job_input.socket.getaddrinfo',resolve)
    with pytest.raises(ValueError,match='Private'):
        public_url('https://internal.example/job')
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(302,headers={'location':'https://internal.example/secret'})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError,match='Private'):
        load_job_url('https://example.com/job',client)
    assert len(calls)==1


def test_blocked_sites_and_large_pages_fail_with_paste_fallback(monkeypatch):
    public_dns(monkeypatch)
    for status,text in [(403,'Sign in'),(200,'x'*1_000_001)]:
        client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(status,headers={'content-type':'text/html'},text=text)))
        with pytest.raises(ValueError,match='[Pp]aste'):
            load_job_url('https://example.com/job',client)


def test_gap_decisions_are_saved_with_run_without_becoming_claims(tmp_path):
    from career_pipeline.pipeline import run
    from career_pipeline.store import Store, digest
    from career_pipeline.models import Settings
    c = Career.model_validate_json((Path(__file__).resolve().parents[1] / 'fixtures/career.json').read_text())
    jd = 'Required: Kubernetes production administration.'
    store = Store(str(tmp_path/'runs.sqlite'))
    store.event('intake-' + digest(jd), 'follow_up', {'requirement_id':'q1','answer':'No relevant experience','kind':'gap'})
    m = run(jd, c, store, Settings(), style_path=Path(__file__).resolve().parents[1]/'writing_style')
    assert m['status'] == 'needs_review'
    assert m['follow_up_answers']['q1']['answer'] == 'No relevant experience'
    assert m['requirements'][0]['classification'] == 'unsupported'
    assert not any('Kubernetes' in claim['text'] for v in m['versions'] for claim in v['packet']['resume'])
