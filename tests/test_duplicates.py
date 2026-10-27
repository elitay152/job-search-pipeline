"""The same degree or publication saved twice in different formats; synthetic data only."""
from pathlib import Path
from career_pipeline.models import Career, Evidence
from career_pipeline.duplicates import duplicate_groups, merge_duplicates
from career_pipeline.resume_intake import merge_resume
from career_pipeline.pipeline import run
from career_pipeline.store import Store


def record(ident, kind, text, status='user_provided'):
    return Evidence(id=ident, kind=kind, project=text[:40], confirmed_statements=[text], actions=[],
                    ownership='unspecified', technologies=[], sources=[{'reference': 'source ' + ident, 'status': status}])


CONFIRMED = [record('degree', 'education', 'Master of Science in Data Analytics | Example University | 2023-06', 'user_confirmed'),
             record('paper', 'publication', 'Morgan, E. (2026). Governing Synthetic Pipelines. Journal of Examples, 1(1).', 'user_confirmed')]
IMPORTED = [record('degree-copy', 'education', 'Master of Science in Data Analytics | Example University | Salt Lake City, UT | June 2023'),
            record('paper-copy', 'publication', '- Morgan, E., (2026). Governing synthetic pipelines. Journal of Examples, 1(1), 1-9.'),
            record('other-degree', 'education', 'Master of Science in Data Analytics | Different College | 2019-06')]


def test_same_degree_or_title_is_a_duplicate_but_other_institutions_are_not():
    career = Career(display_name='Synthetic', evidence=CONFIRMED + IMPORTED)
    assert sorted([e.id for e in group] for group in duplicate_groups(career)) == [
        ['degree', 'degree-copy'], ['paper', 'paper-copy']]
    merged, report = merge_duplicates(career)
    assert sorted(e.id for e in merged.evidence) == ['degree', 'other-degree', 'paper']
    kept = next(e for e in merged.evidence if e.id == 'degree')
    assert {s.reference for s in kept.sources} == {'source degree', 'source degree-copy'}
    assert {item['kept'] for item in report} == {'degree', 'paper'}


def test_resume_reimport_does_not_add_a_second_copy():
    existing = Career(display_name='Synthetic', evidence=CONFIRMED)
    combined = merge_resume(existing, Career(display_name='Synthetic', evidence=IMPORTED[:2]))
    assert [e.id for e in combined.evidence] == ['degree', 'paper']
    assert {s.reference for s in combined.evidence[0].sources} == {'source degree', 'source degree-copy'}


def test_drafts_render_one_copy_even_before_merging(tmp_path):
    career = Career.model_validate_json(Path('fixtures/career.json').read_text())
    career.evidence += [record('degree', 'education', 'Master of Science in Data Analytics | Example University | 2023-06', 'user_confirmed'),
                        record('degree-copy', 'education', 'Master of Science in Data Analytics | Example University | June 2023')]
    m = run(Path('fixtures/job.txt').read_text(), career, Store(str(tmp_path / 'runs.sqlite')))
    cited = {i for claim in m['versions'][-1]['packet']['resume'] for i in claim['evidence_ids']}
    assert 'degree-copy' not in m['selected_evidence'] and 'degree-copy' not in cited
