"""Synthetic reproductions of scope errors discovered in saved live drafts."""
import pytest
from career_pipeline.models import Evidence
from career_pipeline.grounding import deterministic_objections


def evidence(text):
    return Evidence(id='delivery', project='Synthetic delivery', actions=[], ownership='contributed',
                    technologies=[], confirmed_statements=[text],
                    sources=[{'reference':'synthetic://resume', 'status':'user_provided'}])


@pytest.mark.parametrize('claim', [
    'Implemented CI/CD pipelines for production releases.',
    'Built GitHub Actions workflows.',
    'My experience includes implementing CI/CD pipelines.',
])
def test_deploying_is_not_authoring(claim):
    source = evidence('Deployed production code through GitHub CI/CD.')
    assert 'deployment use upgraded to CI/CD authorship' in deterministic_objections(claim, [source])


@pytest.mark.parametrize('text', [
    'Built Python pipelines and deployed them via CI/CD.',
    'Developed production code using CI/CD.',
    'Deployed production code through GitHub CI/CD.',
    'Implemented CI/CD pipelines for production releases.',
])
def test_actual_source_scope_is_not_rejected(text):
    assert 'deployment use upgraded to CI/CD authorship' not in deterministic_objections(text, [evidence(text)])


def test_unrelated_project_topics_do_not_establish_training_topics():
    source = evidence('Trained 10 colleagues. Worked on optimization and deployments.')
    findings = deterministic_objections('Trained 10 colleagues on optimization and deployments.', [source])
    assert 'unestablished peer-training topic: optimization' in findings
    assert 'unestablished peer-training topic: deployment' in findings
    assert not deterministic_objections('Trained 10 colleagues.', [source])


def test_explicit_source_training_topics_are_supported():
    source = evidence('Trained 10 colleagues on optimization and deployments.')
    assert not deterministic_objections(source.confirmed_statements[0], [source])


def test_peer_training_alternative_source_wording():
    source = evidence('Provided peer training on Python. Trained 10 colleagues.')
    assert not deterministic_objections('Trained 10 colleagues on Python.', [source])
