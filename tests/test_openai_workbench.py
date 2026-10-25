"""Exercise the real SDK and UI flow using synthetic HTTP responses, never paid calls."""
import json
from pathlib import Path
import httpx
from docx import Document
from streamlit.testing.v1 import AppTest
from career_pipeline.models import Career
from test_ui import workspace, field, ROOT
from test_openai_provider import install_transport, response


def test_openai_revision_truncation_approval_and_downloads(workspace, monkeypatch):
    career = Career.model_validate_json((workspace/'fixtures/career.json').read_text())
    statements = ['Deployed production Python code through GitHub CI/CD.',
                  'Trained 10 colleagues. Worked on optimization and deployments.']
    for e, statement in zip(career.evidence, statements):
        e.approved_wording = []
        e.confirmed_statements = [statement]
        e.actions = [statement]
        e.metrics = []
    (workspace/'local').mkdir()
    (workspace/'local/career.json').write_text(career.model_dump_json(), encoding='utf-8')
    revised = {
        'resume': [
            {'id':'r1', 'text':'Deployed Python production code via GitHub CI/CD.', 'evidence_ids':['ev-pipeline']},
            {'id':'r2', 'text':'Provided peer training to 10 colleagues.', 'evidence_ids':['ev-orchestration']}],
        'cover_letter': [{'id':'c1', 'text':'My experience deploying Python code through GitHub CI/CD aligns with the delivery work in this role.', 'evidence_ids':['ev-pipeline']}],
        'skills':['ev-pipeline', 'ev-orchestration']}
    initial = json.loads(json.dumps(revised))
    initial['resume'][0]['text'] = 'Implemented CI/CD pipelines for production Python code.'
    initial['resume'][1]['text'] = 'Trained 10 colleagues on optimization and deployments.'
    calls = []
    truncated = False
    def handler(request):
        nonlocal truncated
        wire = json.loads(request.content)
        envelope = json.loads(wire['messages'][1]['content'])
        task, data = envelope['task'], envelope['data']
        calls.append((task, data.get('role')))
        if task in ('generate', 'revise'):
            result = initial if task == 'generate' else revised
        else:
            claims = data['packet']['resume'] + data['packet']['cover_letter']
            result = {'findings':[], 'reviewed_claim_ids':[c['id'] for c in claims], 'assessments':[]}
            if data['role'] == 'evidence':
                if len(claims) > 1 and not truncated:
                    truncated = True
                    return httpx.Response(200, json=response({}, status='incomplete'))
                catalog = data['source_quotes']
                for c in claims:
                    quotes = []
                    for ident in c['evidence_ids']:
                        qid = next(k for k,v in catalog.items() if ident in v['evidence_ids']
                                   and v['text'] in statements)
                        quotes.append({'evidence_id':ident, 'source_quote_id':qid})
                    result['assessments'].append(dict(claim_id=c['id'], evidence_ids=c['evidence_ids'],
                        quotes=quotes, wording_supported=True, metrics_consistent=True,
                        technology_consistent=True, scope_consistent=True, dates_titles_consistent=True))
        return httpx.Response(200, json=response(result))
    install_transport(monkeypatch, handler)
    app = AppTest.from_file(str(ROOT/'career_pipeline/ui.py')).run()
    field(app, 'radio', 'Generation mode').set_value('Use OpenAI').run()
    field(app, 'text_area', 'Paste the job description').set_value('Required: Python delivery and peer training. Git version control.').run()
    field(app, 'button', 'Create my draft').click().run(timeout=20)
    assert not app.exception
    assert truncated
    assert calls[:2] == [('generate',None), ('revise',None)]  # Repair before paid reviews.
    assert ('review','evidence') in calls and ('review','recruiter') in calls and ('review','voice') in calls
    field(app, 'button', 'Prepare documents').click().run()
    assert all(Path(p).parent.name == 'draft' for p in app.session_state['downloads'])
    field(app, 'checkbox', 'I reviewed the wording, supporting evidence, dates and unresolved gaps.').check().run()
    assert not field(app, 'button', 'Approve this application').disabled
    field(app, 'button', 'Approve this application').click().run()
    assert not app.exception
    paths = [Path(p) for p in app.session_state['downloads'] if p.endswith('.docx')]
    assert len(paths) == 2
    for path in paths:
        assert path.parent.name == 'final'
        text = '\n'.join(p.text for p in Document(path).paragraphs)
        assert 'DRAFT' not in text and 'ev-pipeline' not in text
        assert 'Implemented CI/CD' not in text and 'on optimization' not in text
        assert 'Python' in text
    total = len(calls)
    fresh = AppTest.from_file(str(ROOT/'career_pipeline/ui.py')).run()
    assert not fresh.exception
    assert (workspace/'local/career.json').exists()
    assert len(calls) == total  # Restarting the UI does not regenerate or charge again.
