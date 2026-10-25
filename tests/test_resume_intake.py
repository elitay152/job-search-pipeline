import io
import pytest
from docx import Document
from career_pipeline.resume_intake import ResumeIntake, IntakeJob, read_resume, to_career, merge_resume, extract_resume

TEXT = '''Morgan Example
morgan@example.test
Data Engineer | Synthetic Co | January 2023 – Present
Built Python ingestion with duplicate checks.
Education
MS, Example University, 2022.
Skills
Azure Data Factory (training)
'''


def parsed():
    return ResumeIntake(name='Morgan Example', contact=['morgan@example.test'],
        jobs=[IntakeJob(employer='Synthetic Co', title='Data Engineer', start='2023-01', end=None,
            header_quote='Data Engineer | Synthetic Co | January 2023 – Present',
            bullets=['Built Python ingestion with duplicate checks.'])], education=['MS, Example University, 2022.'],
        publications=[], skills=['Azure Data Factory (training)'])


def test_docx_and_txt_upload_preserve_source_text():
    document=Document()
    for line in TEXT.splitlines():document.add_paragraph(line)
    target=io.BytesIO();document.save(target)
    assert read_resume(target.getvalue(),'resume.docx').strip() == TEXT.strip()
    assert read_resume(TEXT.encode(),'resume.txt') == TEXT
    with pytest.raises(ValueError,match='DOCX'):
        read_resume(b'fake data','resume.pdf')


def test_source_inputs_are_usable_without_fact_confirmation_and_merge_is_repeatable():
    imported=to_career(parsed(),TEXT,'synthetic upload')
    assert all(e.eligible and e.sources[0].status=='user_provided' for e in imported.evidence)
    assert imported.evidence[-1].technologies[0].context=='training'
    again=merge_resume(imported,imported)
    assert len(again.evidence)==len(imported.evidence)
    assert len(again.employments)==1


@pytest.mark.parametrize('change', ['invented_bullet','invented_date','empty_job','wrong_employer'])
def test_extraction_cannot_introduce_facts_or_empty_jobs(change):
    result=parsed()
    if change=='invented_bullet':result.jobs[0].bullets=['Managed 50 engineers.']
    if change=='invented_date':result.jobs[0].start='2020-01'
    if change=='empty_job':result.jobs[0].bullets=[]
    if change=='wrong_employer':result.jobs[0].employer='Invented Co'
    with pytest.raises(ValueError):to_career(result,TEXT,'synthetic upload')


def test_intake_adapter_uses_resume_schema_and_keeps_raw_input_untrusted(monkeypatch):
    from career_pipeline.providers import OpenAIProvider
    def fake(self,task,payload,model,max_tokens):
        assert task=='intake' and payload['resume_lines'][0]=={'id':0,'text':'Morgan Example'}
        assert self.max_attempts==1 and max_tokens==12000
        return {'result':{'name_line_id':0,'contact_line_ids':[1], 'jobs':[{'employer':'Synthetic Co','title':'Data Engineer','start':'2023-01','end':None,'header_line_ids':[2],'bullet_line_ids':[3]}], 'education_line_ids':[5],'publication_line_ids':[],'skill_line_ids':[7]}}
    monkeypatch.setattr(OpenAIProvider,'complete',fake)
    career,text=extract_resume(TEXT.encode(),'resume.txt')
    assert text==TEXT and career.employments[0].employer=='Synthetic Co'


def test_changed_display_title_does_not_create_duplicate_job():
    from career_pipeline.models import Employment
    imported=to_career(parsed(),TEXT,'synthetic upload')
    existing=imported.model_copy(deep=True)
    existing.employments[0].official_title='Analyst III'
    existing.employments[0].resume_display_title='Data Engineer'
    existing.employments[0].resume_display_title_approved=True
    merged=merge_resume(existing,imported)
    assert len(merged.employments)==1
    assert merged.employments[0].official_title=='Analyst III'


def test_conflicting_dates_do_not_overwrite_or_duplicate_saved_history():
    imported=to_career(parsed(),TEXT,'synthetic upload')
    existing=imported.model_copy(deep=True)
    existing.employments[0].start='2022-01'
    with pytest.raises(ValueError,match='dates conflict'):
        merge_resume(existing,imported)
    assert existing.employments[0].start=='2022-01'


def test_extraction_cannot_silently_omit_a_source_bullet():
    with pytest.raises(ValueError,match='omitted a source bullet'):
        to_career(parsed(),TEXT+'\n- Built SQL validation checks.','synthetic upload')


def test_indexed_intake_preserves_punctuation_and_multiline_headers():
    from career_pipeline.resume_intake import IndexedResumeIntake,from_line_selection
    lines=['Morgan Example','Synthetic Co','Data Engineer','January 2023 – Present',
           'Built “exact-source” Python ingestion—estimated savings of 20 hours/month.']
    selected=IndexedResumeIntake(name_line_id=0, contact_line_ids=[],jobs=[dict(employer='Synthetic Co',title='Data Engineer',start='2023-01',end=None,header_line_ids=[1,2,3],bullet_line_ids=[4])],education_line_ids=[],publication_line_ids=[],skill_line_ids=[])
    result=to_career(from_line_selection(selected,lines),'\n'.join(lines),'synthetic upload')
    assert result.evidence[0].supported_wording[0]==lines[4]
    selected.jobs[0].bullet_line_ids=[999]
    with pytest.raises(ValueError,match='invalid source line'):
        from_line_selection(selected,lines)


def test_indexed_intake_correction_is_bounded(monkeypatch):
    from career_pipeline.providers import OpenAIProvider
    calls=[]
    def fake(self,task,payload,model,max_tokens):
        calls.append(payload)
        return {'result':{'name_line_id':999,'contact_line_ids':[], 'jobs':[], 'education_line_ids':[],'publication_line_ids':[],'skill_line_ids':[]}}
    monkeypatch.setattr(OpenAIProvider,'complete',fake)
    with pytest.raises(ValueError,match='invalid source line'):
        extract_resume(TEXT.encode(),'resume.txt')
    assert len(calls)==2 and 'correction' in calls[-1]


def test_indexed_intake_keeps_technical_projects_instead_of_dropping_their_bullets():
    from career_pipeline.resume_intake import IndexedResumeIntake,from_line_selection
    lines=[line for line in TEXT.splitlines() if line] + ['Technical Projects','Synthetic monitoring project','- Built a Python monitoring prototype.']
    selection=IndexedResumeIntake(name_line_id=0,contact_line_ids=[1],
        jobs=[dict(employer='Synthetic Co',title='Data Engineer',start='2023-01',end=None,header_line_ids=[2],bullet_line_ids=[3])],
        education_line_ids=[5],publication_line_ids=[],skill_line_ids=[7],
        projects=[dict(title_line_id=9,statement_line_ids=[10])])
    result=to_career(from_line_selection(selection,lines),'\n'.join(lines),'synthetic upload')
    assert any(e.kind=='project' and 'monitoring prototype' in e.supported_wording[0] for e in result.evidence)
