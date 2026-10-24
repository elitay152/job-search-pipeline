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
    return {'id':'resp_synthetic','object':'response','created_at':0,'status':status,'model':'gpt-4.1',
        'output':[{'type':'function_call','id':'fc_synthetic','call_id':'call_synthetic',
                   'name':'return_result','arguments':json.dumps(result)}],
        'usage':{'input_tokens':30,'output_tokens':20,'total_tokens':50,
                 'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':0}}}


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
        assert request.url.path=='/v1/responses'
        body=json.loads(request.content);calls.append(body)
        assert body['tools'][0]['strict'] is True
        assert body['tool_choice']=={'type':'function','name':'return_result'}
        assert 'APPROVED_STYLE' not in body['input'][0]['content']
        assert 'APPROVED_STYLE' in body['instructions']
        task=json.loads(body['input'][0]['content'])['task']
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
    assert 'adversarial evidence auditor' in calls[1]['instructions']
    assert 'skeptical recruiter' in calls[2]['instructions']
    assert 'voice editor' in calls[3]['instructions']


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
    assert settings.generator_model=='gpt-4.1' and settings.reviewer_model=='claude-sonnet-4-5'
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
        envelope=json.loads(body['input'][0]['content'])
        payload=envelope['data'];payload['style']='synthetic approved guidance'
        called.append((envelope['task'],payload.get('role')))
        result=MockProvider().complete(envelope['task'],payload,'synthetic-model')
        if envelope['task']=='review':result['assessments']=[]
        return httpx.Response(200,json=response(result))
    install_transport(monkeypatch,handler)
    career=Career.model_validate_json(Path('fixtures/career.json').read_text())
    store=Store(str(tmp_path/'openai.sqlite'))
    settings=Settings(generator='openai',reviewer='openai',factual_mode='model_reviewed')
    m=run(Path('fixtures/job.txt').read_text(),career,store,settings)
    assert called==[('generate',None),('review','evidence'),('review','recruiter'),('review','voice')]
    assert m['settings']['reviewer']=='openai' and not m['validation']
    assert all(t['provider']=='openai' for t in m['telemetry'])
    assert all(t['input_tokens']==30 and t['output_tokens']==20 for t in m['telemetry'])
    approve(store,m['id'],career,True)
    assert store.get(m['id'])['approved']
