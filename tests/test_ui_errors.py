from career_pipeline.ui_errors import configuration_problem, failure_message


def test_missing_key_and_explicit_binding(monkeypatch):
    for name in ('CAREER_OPENAI_KEY_VARIABLE','CAREER_OPENAI_API_KEY','OPENAI_API_KEY'):
        monkeypatch.delenv(name,raising=False)
    assert 'missing on this computer' in configuration_problem('openai')
    monkeypatch.setenv('CAREER_OPENAI_KEY_VARIABLE','SYNTHETIC_BINDING')
    monkeypatch.setenv('SYNTHETIC_BINDING','synthetic-secret')
    assert configuration_problem('openai') is None
    assert configuration_problem('mock') is None


def test_provider_errors_do_not_echo_exception_content():
    class Error(Exception):
        status_code=401
    assert 'rejected' in failure_message(Error('sensitive-response-content'))
    assert 'sensitive-response-content' not in failure_message(Error('sensitive-response-content'))
    assert 'private facts' not in failure_message(ValueError('private facts'))


def test_known_review_and_output_failures_are_actionable():
    from career_pipeline.diagnostics import failure_details
    assert failure_details(ValueError('Evidence reviewer did not account for every claim'))['code']=='review_contract_invalid'
    message=failure_message(ValueError('OpenAI response incomplete; no candidate or review accepted'))
    assert 'per-call output limit' in message
    assert 'total token budget' in message


def test_schema_failure_does_not_expose_bad_input():
    from pydantic import ValidationError
    from career_pipeline.models import Packet
    from career_pipeline.diagnostics import failure_details
    try:
        Packet.model_validate({'resume':'private document text'})
    except ValidationError as exc:
        detail=failure_details(exc)
    assert detail['code']=='response_schema_invalid'
    assert 'private document text' not in str(detail)
