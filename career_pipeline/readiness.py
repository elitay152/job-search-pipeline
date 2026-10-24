"""Explicit synthetic provider checks; no user documents or secrets in results."""
import subprocess
import time
from pathlib import Path
from .diagnostics import failure_details
from .models import Packet, Career, Settings
from .providers import OpenAIProvider, AnthropicProvider, MockProvider
from .pipeline import validate_review_contract
from .ui_errors import configuration_problem


def app_version():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            timeout=2, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        from importlib.metadata import version
        return version('career-evidence-pipeline')


def budget_plan(settings):
    cycles = settings.max_revisions + 1
    return {'normal_calls': 4 * cycles, 'with_contract_corrections': 7 * cycles,
            'call_budget': settings.max_calls, 'token_budget': settings.token_budget,
            'output_limit': settings.max_output_tokens}


def check_provider(provider, model, role='generator'):
    """One bounded request through the actual adapter, using only fictional data."""
    problem = configuration_problem(provider)
    if problem:
        return {'status': 'failed', 'message': problem, 'provider': provider, 'model': model}
    evidence = {'id': 'synthetic-e1', 'project': 'Synthetic pipeline',
        'confirmed_statements': ['Built Python pipelines.'],
        'actions': ['Built Python pipelines.'], 'ownership': 'contributed', 'technologies': [],
        'sources': [{'reference': 'Synthetic fixture', 'status': 'user_confirmed'}]}
    career = Career(display_name='Synthetic Example', evidence=[evidence])
    packet = Packet(resume=[{'id': 'synthetic-r1', 'text': 'Built Python pipelines.',
                            'evidence_ids': ['synthetic-e1']}], cover_letter=[], skills=[])
    payload = {'job_description': 'Required: Python data pipelines.', 'requirements': [],
        'evidence': career.model_dump(mode='json')['evidence'], 'style': 'Use concise professional language.',
        'factual_mode': 'strict', 'document_plan': None}
    task = 'review' if role == 'reviewer' else 'generate'
    if task == 'review':
        payload.update(role='recruiter', career=career.model_dump(mode='json'), packet=packet.model_dump())
    started = time.monotonic()
    try:
        adapter = {'openai': OpenAIProvider, 'anthropic': AnthropicProvider, 'mock': MockProvider}[provider]()
        adapter.max_attempts = 1
        raw = adapter.complete(task, payload, model) if provider == 'mock' else adapter.complete(task, payload, model, 1500)
        result = raw if provider == 'mock' else raw['result']
        if task == 'review':
            validate_review_contract(result, 'recruiter', packet, [], career, 'strict')
        else:
            Packet.model_validate(result)
        return {'status': 'passed', 'provider': provider, 'model': model, 'role': role,
                'latency': time.monotonic() - started,
                'input_tokens': raw.get('input_tokens', 0), 'output_tokens': raw.get('output_tokens', 0),
                'message': 'Synthetic structured request passed. This does not certify a full application run.'}
    except Exception as exc:
        return dict(failure_details(exc), status='failed', provider=provider, model=model,
                    role=role, latency=time.monotonic() - started)
