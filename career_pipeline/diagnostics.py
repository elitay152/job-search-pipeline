"""Allowlisted, content-free explanations safe for UI and run manifests."""
from pydantic import ValidationError

CONTRACT_ERRORS = {
    'Reviewer returned findings for the wrong role': 'The reviewer returned findings for a different review role.',
    'Reviewer cited an unknown passage': 'The reviewer cited a passage that is not in this document version.',
    'Reviewer cited an unknown requirement': 'The reviewer cited a job requirement that does not exist.',
    'Reviewer cited unknown evidence': 'The reviewer cited evidence that is not in the saved library.',
    'Reviewer finding must identify a passage, section or requirement': 'A reviewer finding has no document or requirement reference.',
    'Evidence reviewer did not account for every claim': 'The evidence reviewer omitted one or more resume or cover-letter claims from its inspection receipt.',
    'Auditor assessed an unknown claim': 'The evidence reviewer assessed a claim that is not in this document version.',
    'Duplicate claim support assessment': 'The evidence reviewer returned duplicate assessments for one claim.',
    'Support assessment does not match cited evidence': 'The evidence reviewer used a different set of evidence references than the claim being checked.',
    'Support quote references uncited evidence': 'The evidence reviewer quoted a source that the claim does not cite.',
}


def failure_details(exc):
    code, message = 'unclassified_failure', f'Run stopped ({type(exc).__name__}). The saved failure stage identifies where it stopped; no document or credential contents are included in this diagnostic.'
    if isinstance(exc, ValidationError):
        code, message = 'response_schema_invalid', 'Structured data did not match the required schema. The candidate or review was not accepted. Inspect the saved stage; changing your API key will not fix this schema error.'
    elif isinstance(exc, ValueError):
        value = str(exc)
        if value == 'Every saved job needs source bullets before generation. Add accomplishments under My experience; no empty job section will be exported.':
            code, message = 'missing_source_bullets', value
        elif value == 'provider call/token budget exhausted before request':
            code, message = 'budget_exhausted', 'The run reached its call/token budget before the next request. Increase the budget under Writing style & advanced settings, or use fewer revision cycles. No request was sent for the blocked stage.'
        elif value in CONTRACT_ERRORS:
            code, message = 'review_contract_invalid', CONTRACT_ERRORS[value] + ' The review was not accepted; saved attempts show whether the bounded correction was used.'
        elif value == 'OpenAI response incomplete; no candidate or review accepted':
            code, message = 'response_incomplete', 'The model did not return a complete tool result. Its output may have reached the per-call output limit. Check that limit separately from the total token budget; no incomplete result was accepted.'
        elif value == 'Expected exactly one structured OpenAI result':
            code, message = 'structured_result_missing', 'The model did not return exactly one required structured result. No candidate or review was accepted.'
        elif value == 'Writing profile must be approved or use the labeled neutral default':
            code, message = 'style_unapproved', 'Choose an approved writing profile or the bundled neutral default.'
        elif value == 'Job description must contain 20–50,000 characters':
            code, message = 'job_input_invalid', 'Paste a job description between 20 and 50,000 characters.'
    status = getattr(exc, 'status_code', None)
    if status == 401:
        code, message = 'provider_authentication', 'The provider rejected the API key. Check the key configured on this computer and restart Streamlit after changing it.'
    elif status == 429:
        code, message = 'provider_quota', 'The provider reported a quota or rate limit. Check API billing and project limits; ChatGPT subscriptions do not include API credits.'
    elif status in (403,404):
        code, message = 'provider_access', 'The provider denied access to the requested model or endpoint. Check the selected model and project permissions.'
    elif type(exc).__name__ in ('APIConnectionError','APITimeoutError','ConnectError','TimeoutException'):
        code, message = 'provider_connection', 'Could not reach the model provider. Check your network, proxy and firewall settings.'
    return {'code': code, 'message': message, 'exception_type': type(exc).__name__}


def failure_message(exc):
    return failure_details(exc)['message']
