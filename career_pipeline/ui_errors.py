"""Actionable provider diagnostics without displaying SDK messages or credentials."""
import os


def configuration_problem(provider):
    if provider == 'openai':
        from .providers import openai_key
        try:
            openai_key()
        except RuntimeError:
            return 'OpenAI API key missing on this computer. Set CAREER_OPENAI_API_KEY (or OPENAI_API_KEY) in the environment used to launch Streamlit, then restart the app. The cloud workspace key is not transferred to your computer.'
    if provider == 'anthropic' and not os.environ.get('ANTHROPIC_API_KEY'):
        return 'Anthropic API key missing. Set ANTHROPIC_API_KEY in the environment used to launch Streamlit, then restart the app.'
    return None


def failure_message(exc):
    if isinstance(exc, ValueError) and str(exc) == 'provider call/token budget exhausted before request':
        return 'The run reached its call/token budget before the next request. Increase the budget under Writing style & advanced settings, or use fewer revision cycles. No request was sent for the blocked stage.'
    status = getattr(exc, 'status_code', None)
    if status == 401:
        return 'The provider rejected the API key. Check the key configured on this computer and restart Streamlit after changing it.'
    if status == 429:
        return 'The provider reported a quota or rate limit. Check API billing and project limits; ChatGPT subscriptions do not include API credits.'
    if status in (403, 404):
        return 'The provider denied access to the requested model or endpoint. Check the selected model and project permissions.'
    if type(exc).__name__ in ('APIConnectionError', 'APITimeoutError', 'ConnectError', 'TimeoutException'):
        return 'Could not reach the model provider. Check your network, proxy and firewall settings.'
    return f'Run stopped ({type(exc).__name__}). Saved progress is available in History. Check model settings, budgets and the technical audit stages.'
