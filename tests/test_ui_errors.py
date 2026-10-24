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
