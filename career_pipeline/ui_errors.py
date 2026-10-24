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



from .diagnostics import failure_message  # Backward-compatible UI import.
