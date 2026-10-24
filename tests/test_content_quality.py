from pathlib import Path
import pytest
from career_pipeline.models import Career, Evidence, Employment, Claim, Packet, Settings, ContentQualitySettings
from career_pipeline.content_quality import check_content_quality
from career_pipeline.pipeline import run
from career_pipeline.review import audit
from career_pipeline.store import Store
from career_pipeline.export import approve
from career_pipeline.providers import OpenAIProvider


def weak_case():
    jobs=[Employment(id='old',employer='Synthetic Old Co',official_title='Analyst',start='2020-01',end='2022-01'),
          Employment(id='new',employer='Synthetic New Co',official_title='Engineer',start='2023-01')]
    texts=['Wrote queries.', 'Database size: approximately 3e+06 records.',
           'Active member population: approximately 42000 members.']
    evidence=[Evidence(id=f'e{i}',employment_ids=['old'] if i<2 else ['new'],project='Synthetic warehouse',
        actions=[text],ownership='contributed',technologies=[],confirmed_statements=[text],
        sources=[{'reference':'synthetic://user','status':'user_confirmed'}]) for i,text in enumerate(texts)]
    c=Career(display_name='Morgan Synthetic',employments=jobs,evidence=evidence)
    p=Packet(resume=[Claim(id=f'r{i}',text=t,evidence_ids=[f'e{i}']) for i,t in enumerate(texts)],
        cover_letter=[Claim(id=f'c{i}',text=texts[i],evidence_ids=[f'e{i}']) for i in (1,2)])
    return c,p


def test_factually_supported_document_can_have_presentation_problems():
    c,p=weak_case()
    assert not audit(p,c)
    findings=check_content_quality(p,c,ContentQualitySettings())
    codes={f.code for f in findings}
    assert {'fragmented_bullet','scientific_notation','ledger_fragment','disconnected_letter','experience_order'}<=codes
    assert all(f.severity=='suggestion' and (f.claim_id or f.section) for f in findings)


def test_cross_employer_scope_and_repetition_are_explicit():
    c,p=weak_case()
    p.resume.append(Claim(id='mixed',text='Supported data pipelines at both employers.',evidence_ids=['e0','e2']))
    p.resume.append(p.resume[0].model_copy(update={'id':'repeat'}))
    found=check_content_quality(p,c,ContentQualitySettings())
    assert any(f.code=='mixed_employer_scope' and f.claim_id=='mixed' for f in found)
    assert any(f.code=='repeated_passage' and f.claim_id=='repeat' for f in found)


def test_configurable_preferences_and_disabled_checks():
    c,p=weak_case()
    assert not check_content_quality(p,c,ContentQualitySettings(enabled=False))
    findings=check_content_quality(p,c,ContentQualitySettings(minimum_bullet_words=0,minimum_letter_words=100,
        check_number_display=False,check_role_structure=False))
    assert any(f.code=='thin_letter' for f in findings)
    assert not {'fragmented_bullet','scientific_notation','experience_order'} & {f.code for f in findings}


def test_education_and_citations_are_not_short_experience_bullets():
    c,p=weak_case()
    c.evidence[0].kind='education'
    c.evidence[0].confirmed_statements=['MS, Example University.']
    p.resume[0].text='MS, Example University.'
    assert not any(f.code=='fragmented_bullet' and f.claim_id=='r0' for f in check_content_quality(p,c,ContentQualitySettings()))


def test_normal_scientific_tool_names_and_complete_paragraphs_not_flagged():
    c=Career.model_validate_json(Path('fixtures/career.json').read_text())
    p=Packet(resume=[Claim(id='r',text='Built Python validation checks for reliable daily ingestion.',evidence_ids=['ev-pipeline'])],
        cover_letter=[Claim(id='c',text='My Python ingestion work aligns with the pipeline responsibilities in this role. I contributed validation checks to support reliable delivery.',evidence_ids=['ev-pipeline'])])
    assert not check_content_quality(p,c,ContentQualitySettings())


def test_quality_warnings_survive_review_and_do_not_waive_factual_gate(monkeypatch,tmp_path):
    c,p=weak_case()
    def complete(self,task,payload,model,max_tokens=6000):
        result={'findings':[], 'reviewed_claim_ids':[claim.id for claim in p.resume+p.cover_letter], 'assessments':[]}
        return {'result':result,'input_tokens':10,'output_tokens':10}
    monkeypatch.setattr(OpenAIProvider,'complete',complete)
    store=Store(str(tmp_path/'runs.sqlite'))
    m=run('Required: warehouse queries and records.',c,store,
        Settings(generator='openai',reviewer='openai',max_revisions=0,factual_mode='model_reviewed'),seed_packet=p)
    assert m['versions'][0]['content_quality_status']=='assessed'
    assert 'scientific_notation' in {f['code'] for f in m['versions'][0]['findings']}
    assert m['stopping_reason']=='revision_limit' and not m['validation']
    approve(store,m['id'],c,True)  # Presentation warnings are reviewable, not factual blockers.
    p.resume[0].text='Managed 50 engineers.'
    m=run('Required: warehouse queries and records.',c,store,
        Settings(generator='openai',reviewer='openai',max_revisions=0,factual_mode='model_reviewed'),seed_packet=p)
    assert m['status']=='needs_review'
    with pytest.raises(ValueError):approve(store,m['id'],c,True)


def test_missing_selected_skill_category_is_visible():
    c=Career.model_validate_json(Path('fixtures/career.json').read_text())
    c.evidence[0].technologies[0].category='Languages'
    c.evidence[1].technologies[0].category='Orchestration'
    p=Packet(resume=[],cover_letter=[],skills=[c.evidence[0].id])
    findings=check_content_quality(p,c,ContentQualitySettings(),{'skill_evidence':[e.id for e in c.evidence]})
    assert any(f.code=='missing_skill_category' and 'Orchestration' in f.message for f in findings)
