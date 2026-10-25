from pathlib import Path
from career_pipeline.models import Career, Evidence, Employment
from career_pipeline.composition import build_composition_plan
from career_pipeline.pipeline import run
from career_pipeline.providers import MockProvider
from career_pipeline.store import Store


def test_composition_preserves_scope_and_flags_cross_employer_evidence():
    jobs=[Employment(id='old',employer='Old Co',official_title='Engineer',start='2021-01',end='2023-01'),
          Employment(id='new',employer='New Co',official_title='Engineer',start='2023-02')]
    records=[]
    for ident,ids in [('a',['old']),('b',['new']),('shared',['old','new'])]:
        records.append(Evidence(id=ident,employment_ids=ids,project='Pipelines',actions=['Wrote code'],ownership='contributed',technologies=[],
            confirmed_statements=['Wrote code.'],sources=[{'reference':'synthetic','status':'user_confirmed'}]))
    records.append(records[0].model_copy(update={'id':'uncertain','sources':[records[0].sources[0].model_copy(update={'status':'uncertain'})]}))
    c=Career(display_name='Synthetic',employments=jobs,evidence=records)
    plan=build_composition_plan(c,[e.id for e in records])
    sections=plan['experience_sections']
    assert sections[0]['latest_start']=='2023-02'
    assert len(sections)==3
    assert next(s for s in sections if s['evidence_ids']==['shared'])['requires_placement_clarification']
    assert not any('uncertain' in s['evidence_ids'] for s in sections)
    assert next(s for s in sections if s['evidence_ids']==['b'])['employers']==['New Co']


def test_plan_is_persisted_and_passed_to_each_role(monkeypatch,tmp_path):
    original=MockProvider.complete
    seen=[]
    def complete(self,task,payload,model):
        seen.append(payload['composition_plan'])
        return original(self,task,payload,model)
    monkeypatch.setattr(MockProvider,'complete',complete)
    c=Career.model_validate_json(Path('fixtures/career.json').read_text())
    m=run(Path('fixtures/job.txt').read_text(),c,Store(str(tmp_path/'runs.sqlite')))
    assert len(seen)>=4
    assert all(plan==m['composition_plan'] for plan in seen)
    assert len(m['composition_plan']['cover_letter_paragraphs'])==3
    assert not m['validation']
