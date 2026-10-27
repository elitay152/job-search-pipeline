"""OpenAI transport/contract tests use synthetic data and never contact the service."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from career_pipeline.models import Settings, Career
from career_pipeline.providers import OpenAIProvider, ReviewResponse, strict_tool_schema, openai_key
from career_pipeline.pipeline import run
from career_pipeline.export import approve
from career_pipeline.store import Store


def response(result,status='completed'):
    return {'id':'chatcmpl_synthetic','object':'chat.completion','created':0,'model':'gpt-4.1',
        'choices':[{'index':0,'finish_reason':'tool_calls' if status=='completed' else 'length',
            'message':{'role':'assistant','content':None,'tool_calls':[{'id':'call_synthetic',
                'type':'function','function':{'name':'return_result','arguments':json.dumps(result)}}]}}],
        'usage':{'prompt_tokens':30,'completion_tokens':20,'total_tokens':50}}


def install_transport(monkeypatch,handler):
    import openai
    real=openai.OpenAI
    monkeypatch.setenv('CAREER_OPENAI_API_KEY','synthetic-not-a-real-key')
    monkeypatch.delenv('CAREER_OPENAI_KEY_VARIABLE',raising=False)
    monkeypatch.setattr(openai,'OpenAI',lambda **kwargs:real(**kwargs,
        http_client=httpx.Client(transport=httpx.MockTransport(handler))))


def test_openai_generation_and_all_review_roles(monkeypatch):
    calls=[]
    def handler(request):
        assert request.url.path=='/v1/chat/completions'
        body=json.loads(request.content);calls.append(body)
        assert body['tools'][0]['function']['strict'] is True
        assert body['tool_choice']=={'type':'function','function':{'name':'return_result'}}
        assert 'APPROVED_STYLE' not in body['messages'][1]['content']
        assert 'APPROVED_STYLE' in body['messages'][0]['content']
        task=json.loads(body['messages'][1]['content'])['task']
        if task=='review':
            role=json.loads(body['messages'][1]['content'])['data']['role']
            assert body['tools'][0]['function']['parameters']['$defs']['Finding']['properties']['role']['enum']==[role]
        result=({'findings':[],'reviewed_claim_ids':['r1','c1'],'assessments':[]}
                 if task=='review' else {'resume':[{'id':'r1','text':'Built synthetic pipelines.','evidence_ids':['e1']}],
                    'cover_letter':[{'id':'c1','text':'Built synthetic pipelines.','evidence_ids':['e1']}],'skills':[]})
        return httpx.Response(200,json=response(result))
    install_transport(monkeypatch,handler)
    generation=OpenAIProvider().complete('generate',{'style':'APPROVED_STYLE'},'gpt-4.1')
    assert generation['result']['resume'][0]['id']=='r1'
    for role in ('evidence','recruiter','voice'):
        result=OpenAIProvider().complete('review',{'style':'APPROVED_STYLE','role':role},'gpt-4.1')
        assert result['input_tokens']==30 and result['output_tokens']==20
    assert len(calls)==4
    assert 'evidence auditor checking' in calls[1]['messages'][0]['content']
    assert 'skeptical recruiter' in calls[2]['messages'][0]['content']
    assert 'voice editor' in calls[3]['messages'][0]['content']


def test_strict_schema_closes_all_objects_without_mutating_original():
    original=ReviewResponse.model_json_schema()
    closed=strict_tool_schema(original)
    assert original!=closed
    def check(node):
        if isinstance(node,dict):
            assert 'default' not in node
            if node.get('type')=='object' or 'properties' in node:
                assert node['additionalProperties'] is False
                assert set(node['required'])==set(node.get('properties',{}))
            for item in node.values():check(item)
        elif isinstance(node,list):
            for item in node:check(item)
    check(closed)


def test_explicit_existing_key_variable_without_copying(monkeypatch):
    monkeypatch.setenv('CAREER_OPENAI_KEY_VARIABLE','EXISTING_TEST_BINDING')
    monkeypatch.setenv('EXISTING_TEST_BINDING','synthetic-existing-binding')
    assert openai_key()=='synthetic-existing-binding'
    monkeypatch.delenv('EXISTING_TEST_BINDING')
    with pytest.raises(RuntimeError):openai_key()


def test_provider_defaults_and_mixed_configuration():
    settings=Settings(generator='openai',reviewer='anthropic',factual_mode='model_reviewed')
    assert settings.generator_model=='gpt-5-mini' and settings.reviewer_model=='claude-sonnet-4-5'
    assert Settings(reviewer='openai',factual_mode='model_reviewed').reviewer=='openai'
    with pytest.raises(ValidationError):Settings(reviewer='mock',factual_mode='model_reviewed')

@pytest.mark.parametrize('status',[429,500,401])
def test_openai_retries_only_transient_errors(monkeypatch,status):
    import openai
    from career_pipeline import providers
    count=[]
    def handler(request):
        count.append(1)
        return httpx.Response(status,json={'error':{'message':'synthetic error','type':'synthetic_error','code':'synthetic'}})
    install_transport(monkeypatch,handler)
    monkeypatch.setattr(providers.time,'sleep',lambda _:None)
    with pytest.raises(openai.APIStatusError):
        OpenAIProvider().complete('review',{'role':'evidence'},'gpt-4.1')
    assert len(count)==(1 if status==401 else 3)


def test_openai_incomplete_output_rejected(monkeypatch):
    install_transport(monkeypatch,lambda _:httpx.Response(200,json=response({},status='incomplete')))
    with pytest.raises(ValueError,match='incomplete'):
        OpenAIProvider().complete('review',{'role':'evidence'},'gpt-4.1')


def test_openai_routes_through_pipeline_and_approval_gate(monkeypatch,tmp_path):
    from career_pipeline.providers import MockProvider
    called=[]
    def handler(request):
        body=json.loads(request.content)
        envelope=json.loads(body['messages'][1]['content'])
        payload=envelope['data'];payload['style']='synthetic approved guidance'
        called.append((envelope['task'],payload.get('role')))
        if envelope['task'] == 'review' and payload['role'] == 'evidence':
            result = {'findings': [], 'reviewed_claim_ids': [c['id'] for c in payload['packet']['resume'] + payload['packet']['cover_letter']]}
        else:
            result=MockProvider().complete(envelope['task'],payload,'synthetic-model')
        if envelope['task']=='review':result['assessments']=[]
        return httpx.Response(200,json=response(result))
    install_transport(monkeypatch,handler)
    career=Career.model_validate_json(Path('fixtures/career.json').read_text())
    store=Store(str(tmp_path/'openai.sqlite'))
    settings=Settings(generator='openai',reviewer='openai',factual_mode='model_reviewed')
    m=run(Path('fixtures/job.txt').read_text(),career,store,settings)
    assert called==[('generate',None),('review','recruiter'),('review','voice')]
    assert m['versions'][0]['reviews']['evidence']['deterministic_claim_ids']
    assert m['settings']['reviewer']=='openai' and not m['validation']
    assert all(t['provider']=='openai' for t in m['telemetry'])
    assert all(t['input_tokens']==30 and t['output_tokens']==20 for t in m['telemetry'])
    approve(store,m['id'],career,True)
    assert store.get(m['id'])['approved']


def test_complete_tool_result_with_stop_reason(monkeypatch):
    result={"resume":[],"cover_letter":[],"skills":[]}
    body=response(result)
    body["choices"][0]["finish_reason"]="stop"
    install_transport(monkeypatch,lambda _:httpx.Response(200,json=body))
    assert OpenAIProvider().complete("generate",{},"gpt-4.1")["result"]==result


def test_gateway_limits_retries_to_remaining_budget(monkeypatch,tmp_path):
    import openai
    from career_pipeline.providers import Gateway
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(500,json={'error':{'message':'synthetic failure','type':'server_error'}})
    install_transport(monkeypatch,handler)
    monkeypatch.setattr('career_pipeline.providers.input_token_reservation', lambda *args: 12000)
    # A token-based reservation leaves room for only one attempt.
    gateway=Gateway(Store(str(tmp_path/'budget.sqlite')),Settings(generator='openai',token_budget=21000,max_output_tokens=6000))
    with pytest.raises(openai.APIStatusError):
        gateway.call('generate',{'style':'x'*50000})
    assert len(calls)==1
    assert gateway.tokens<=21000


def test_review_schema_rejects_employment_and_passage_ids_as_evidence():
    from jsonschema import validate
    from jsonschema.exceptions import ValidationError as SchemaError
    from career_pipeline.providers import constrain_review_schema
    payload = {'role': 'recruiter', 'packet': {'resume': [{'id': 'passage-1'}]},
               'career': {'evidence': [{'id': 'fact-1'}], 'employments': [{'id': 'job-1'}]},
               'requirements': [{'id': 'q1'}]}
    schema = constrain_review_schema(strict_tool_schema(ReviewResponse.model_json_schema()), payload)
    finding = {'role': 'recruiter', 'claim_id': 'passage-1', 'requirement_id': 'q1',
               'evidence_ids': ['fact-1'], 'severity': 'suggestion', 'section': None,
               'code': 'clarity', 'message': 'Clarify the supported work.'}
    result = {'findings': [finding], 'reviewed_claim_ids': ['passage-1'], 'assessments': []}
    validate(result, schema)
    for wrong_id in ('job-1', 'passage-1', 'invented-fact'):
        finding['evidence_ids'] = [wrong_id]
        with pytest.raises(SchemaError):
            validate(result, schema)
    finding['evidence_ids'] = []
    validate(result, schema)
    finding['claim_id'] = 'fact-1'
    with pytest.raises(SchemaError):
        validate(result, schema)


def test_openai_resume_only_schema_disallows_cover_letter(monkeypatch):
    def handler(request):
        body=json.loads(request.content)
        schema=body['tools'][0]['function']['parameters']
        assert schema['properties']['cover_letter']['maxItems']==0
        return httpx.Response(200,json=response({'resume':[{'id':'r1','text':'Built synthetic pipelines.', 'evidence_ids':['e1']}], 'cover_letter':[], 'skills':[]}))
    install_transport(monkeypatch,handler)
    result=OpenAIProvider().complete('generate',{'document_plan':{'include_cover_letter':False}},'gpt-4.1')
    assert not result['result']['cover_letter']


def test_gateway_counts_actual_requests_not_unused_retry_allowance(monkeypatch, tmp_path):
    from career_pipeline.providers import Gateway
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response({'resume': [], 'cover_letter': [], 'skills': []}))
    install_transport(monkeypatch, handler)
    with Store(str(tmp_path/'budget.sqlite')) as store:
        gateway = Gateway(store, Settings(generator='openai', max_calls=3))
        for i in range(3):
            gateway.call('generate', {'synthetic_request': i})
        assert gateway.calls == len(calls) == 3
        assert gateway.tokens == 150
        with pytest.raises(ValueError, match='budget exhausted'):
            gateway.call('generate', {'synthetic_request': 4})
        assert len(calls) == 3


def test_input_reservation_uses_tokenizer_and_safe_fallback(monkeypatch):
    from career_pipeline.providers import input_token_reservation
    class Encoding:
        def encode(self, text, disallowed_special):
            assert disallowed_special == ()
            return [1] * 100
    monkeypatch.setattr('career_pipeline.providers.model_encoding', lambda model: Encoding())
    assert input_token_reservation('synthetic <|endoftext|>', 'openai', 'gpt-4.1') == 2163
    monkeypatch.setattr('career_pipeline.providers.model_encoding', lambda model: None)
    assert input_token_reservation('synthetic', 'openai', 'unknown') == len(b'synthetic') + 512


def test_model_context_compaction_preserves_exact_source_fields_and_ids():
    from career_pipeline.providers import compact_context
    source = {'reference': 'synthetic', 'status':'user_provided',
              'excerpt': 'Built Python ingestion and validated source identifiers. ' * 8}
    payload = {'career': {'evidence': [
        {'id':f'e{i}', 'sources':[source], 'confirmed_statements':[f'Statement {i}.'],
         'prohibited_inferences':['Do not infer sole ownership or a quantified outcome.'] * 4}
        for i in range(4)]}}
    original = json.loads(json.dumps(payload))
    compact = compact_context(payload)
    assert payload == original
    assert len(json.dumps(compact)) < len(json.dumps(payload))
    for before, after in zip(payload['career']['evidence'], compact['career']['evidence']):
        assert before['id'] == after['id']
        assert before['confirmed_statements'] == after['confirmed_statements']
        for field in ('sources','prohibited_inferences'):
            assert compact['shared_contexts'][after[field]['shared_context']] == before[field]


def test_evidence_quote_selection_reconstructs_original_text_and_rejects_wrong_source():
    from career_pipeline.providers import evidence_quote_protocol, resolve_source_quotes
    from career_pipeline.models import Evidence
    text = 'Built Python ingestion; retained approximately 20 million records.'
    first = Evidence(id='a', project='Synthetic', actions=[], ownership='contributed', technologies=[],
                     confirmed_statements=[text], sources=[{'reference':'synthetic','status':'user_provided'}])
    second = first.model_copy(update={'id':'b', 'confirmed_statements':['Documented SQL queries.']})
    payload = {'role':'evidence','career':{'evidence':[first.model_dump(),second.model_dump()]}}
    schema = ReviewResponse.model_json_schema()
    wire, catalog = evidence_quote_protocol(payload, schema)
    ident = next(key for key, value in catalog.items() if value['text'] == text)
    assert schema['$defs']['SupportQuote']['required'] == ['evidence_id','source_quote_id']
    assert 'confirmed_statements' not in wire['career']['evidence'][0]
    raw = {'assessments':[{'evidence_ids':['a'], 'quotes':[{'evidence_id':'a','source_quote_id':ident}]}]}
    assert resolve_source_quotes(raw,catalog)['assessments'][0]['quotes'][0] == {'evidence_id':'a','text':text}
    with pytest.raises(ValueError,match='uncited evidence'):
        resolve_source_quotes({'assessments':[{'evidence_ids':['b'], 'quotes':[{'evidence_id':'b','source_quote_id':ident}]}]},catalog)


def test_selected_shared_quote_resolves_to_every_cited_record_that_contains_it():
    from career_pipeline.providers import resolve_source_quotes
    catalog = {'q1':{'evidence_ids':['a','b'], 'text':'Shared original source paragraph.'}}
    result = {'assessments':[{'evidence_ids':['a','b'], 'quotes':[{'evidence_id':'a','source_quote_id':'q1'}]}]}
    quotes = resolve_source_quotes(result,catalog)['assessments'][0]['quotes']
    assert quotes == [{'evidence_id':'a','text':'Shared original source paragraph.'},
                      {'evidence_id':'b','text':'Shared original source paragraph.'}]


def test_exhausted_credits_are_not_retried(monkeypatch):
    import openai
    from career_pipeline.diagnostics import failure_details
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,json={'error':{'message':'Synthetic exhausted credit balance',
            'type':'insufficient_quota','code':'credit_balance_exhausted'}})
    install_transport(monkeypatch,handler)
    with pytest.raises(openai.RateLimitError) as caught:
        OpenAIProvider().complete('generate',{},'gpt-4.1')
    assert len(calls)==1
    assert failure_details(caught.value)['code']=='provider_credit_exhausted'


@pytest.mark.parametrize('model,reasoning', [('gpt-5-mini', True), ('gpt-4.1', False)])
def test_reasoning_models_use_completion_token_limit_without_temperature(monkeypatch, model, reasoning):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response({'resume': [], 'cover_letter': [], 'skills': []}))
    install_transport(monkeypatch, handler)
    OpenAIProvider().complete('generate', {}, model, 9000)
    body = bodies[0]
    if reasoning:
        assert body['max_completion_tokens'] == 9000 and body['reasoning_effort'] == 'low'
        assert 'max_tokens' not in body and 'temperature' not in body
    else:
        assert body['max_tokens'] == 9000 and body['temperature'] == 0
        assert 'max_completion_tokens' not in body and 'reasoning_effort' not in body


def test_known_model_prices_give_a_cost_estimate(monkeypatch, tmp_path):
    from career_pipeline.providers import Gateway
    install_transport(monkeypatch, lambda request: httpx.Response(200, json=response(
        {'resume': [], 'cover_letter': [], 'skills': []})))
    gateway = Gateway(Store(str(tmp_path / 'cost.sqlite')), Settings(generator='openai'))
    gateway.call('generate', {'style': 'x'})
    # 30 input and 20 output tokens at gpt-5-mini's $0.25 / $2.00 per million.
    assert gateway.telemetry[-1]['estimated_cost'] == pytest.approx((30 * 0.25 + 20 * 2.00) / 1e6)
    custom = Gateway(Store(str(tmp_path / 'custom.sqlite')), Settings(generator='openai', generator_model='unlisted-model'))
    custom.call('generate', {'style': 'y'})
    assert custom.telemetry[-1]['estimated_cost'] is None
