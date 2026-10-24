"""Public schemas. Month-only dates remain month-only facts."""
import re
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

Period = date | str

def period_parts(value, upper=False):
    if isinstance(value, date):
        return value.year, value.month, value.day
    return int(value[:4]), int(value[5:7]), 31 if upper else 1

def valid_period(value):
    if value is None or isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError('Date must be an ISO date or month string')
    if re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', value) and int(value[:4]) > 0:
        return value
    if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        return date.fromisoformat(value)
    raise ValueError('Use YYYY-MM or a valid YYYY-MM-DD; never invent missing days')

class Source(BaseModel):
    reference: str
    status: Literal['user_confirmed', 'uncertain']
    excerpt: str | None = None

class Technology(BaseModel):
    name: str
    usage: str
    context: Literal['professional', 'portfolio', 'academic', 'training'] = 'professional'
    category: str = 'Tools'

class Metric(BaseModel):
    value: float = Field(allow_inf_nan=False)
    unit: str
    qualifier: Literal['realized', 'estimated', 'expected']

class Employment(BaseModel):
    id: str
    employer: str
    official_title: str
    start: Period
    end: Period | None = None
    resume_display_title: str | None = None
    resume_display_title_approved: bool = False

    @field_validator('start', 'end', mode='before')
    @classmethod
    def periods(cls, value):
        return valid_period(value)

    @model_validator(mode='after')
    def valid(self):
        if self.resume_display_title and not self.resume_display_title_approved:
            raise ValueError('Descriptive resume title requires explicit user approval')
        if self.end and period_parts(self.end, True) < period_parts(self.start):
            raise ValueError('employment end precedes start')
        return self

class Evidence(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]+$')
    kind: Literal['experience', 'project', 'education', 'publication', 'skill'] = 'experience'
    employer: str = ''
    official_title: str = ''
    resume_display_title: str | None = Field(default=None, min_length=1)
    resume_display_title_approved: bool = False
    start: Period | None = None
    end: Period | None = None
    employment_ids: list[str] = []
    project: str
    actions: list[str]
    ownership: Literal['owned', 'contributed', 'familiarity']
    technologies: list[Technology]
    outcomes: list[str] = []
    metrics: list[Metric] = []
    sources: list[Source] = Field(min_length=1)
    approved_wording: list[str] = []
    # Confirmed factual statements need not be called user-approved application wording.
    confirmed_statements: list[str] = []
    fact_details: dict = {}
    prohibited_inferences: list[str] = []
    tags: list[str] = []

    @field_validator('start', 'end', mode='before')
    @classmethod
    def periods(cls, value):
        return valid_period(value)

    @model_validator(mode='after')
    def dates(self):
        if self.resume_display_title and not self.resume_display_title_approved:
            raise ValueError('Descriptive resume title requires explicit user approval')
        if self.end and not self.start:
            raise ValueError('end requires a start date')
        if self.end and period_parts(self.end, True) < period_parts(self.start):
            raise ValueError('employment end precedes start')
        if not self.supported_wording:
            raise ValueError('Evidence needs approved wording or a confirmed factual statement')
        return self

    @property
    def supported_wording(self):
        return self.approved_wording + self.confirmed_statements

    @property
    def eligible(self):
        return all(s.status == 'user_confirmed' for s in self.sources)

class Presentation(BaseModel):
    include_publications: bool = True
    include_education: bool = True
    include_skills: bool = True
    minimum_recent_bullets: int = Field(default=3, ge=1, le=8)

class Career(BaseModel):
    display_name: str
    contact: list[str] = []
    employments: list[Employment] = []
    presentation: Presentation = Field(default_factory=Presentation)
    evidence: list[Evidence]

    @model_validator(mode='after')
    def unique(self):
        if len({e.id for e in self.evidence}) != len(self.evidence):
            raise ValueError('duplicate evidence ID')
        role_ids = {e.id for e in self.employments}
        if len(role_ids) != len(self.employments):
            raise ValueError('duplicate employment ID')
        dates = {}
        for e in [*self.employments, *self.evidence]:
            if isinstance(e, Evidence) and not set(e.employment_ids) <= role_ids:
                raise ValueError('unknown employment reference')
            if not e.official_title or not e.start:
                continue
            key = (e.employer, e.official_title)
            interval = (e.start, e.end)
            if key in dates and dates[key] != interval:
                raise ValueError('conflicting employment dates')
            dates[key] = interval
        return self

class Requirement(BaseModel):
    id: str
    text: str
    excerpt: str
    priority: Literal['required', 'preferred', 'ambiguous']
    kind: Literal['skill', 'constraint'] = 'skill'
    classification: Literal['direct', 'transferable', 'unsupported', 'needs_clarification'] = 'unsupported'
    evidence_ids: list[str] = []

class Claim(BaseModel):
    id: str
    text: str
    evidence_ids: list[str] = Field(min_length=1)

class Packet(BaseModel):
    resume: list[Claim]
    cover_letter: list[Claim]
    skills: list[str] = []  # Evidence IDs; tools/context rendered from immutable snapshot.

class Finding(BaseModel):
    role: Literal['evidence', 'recruiter', 'voice']
    claim_id: str | None = None
    requirement_id: str | None = None
    evidence_ids: list[str] = []
    severity: Literal['error', 'suggestion', 'gap']
    section: str | None = None
    code: str = 'review'
    message: str

DEFAULT_MODELS = {'mock': 'claude-sonnet-4-5', 'anthropic': 'claude-sonnet-4-5', 'openai': 'gpt-4.1'}

class ContentQualitySettings(BaseModel):
    enabled: bool = True
    minimum_bullet_words: int = Field(default=4, ge=0, le=30)
    minimum_letter_words: int = Field(default=0, ge=0, le=400)
    repetition_similarity: float = Field(default=0.9, ge=0.5, le=1.0)
    check_number_display: bool = True
    check_role_structure: bool = True
    check_letter_structure: bool = True


class Settings(BaseModel):
    content_quality: ContentQualitySettings = Field(default_factory=ContentQualitySettings)
    generator: Literal['mock', 'anthropic', 'openai'] = 'mock'
    reviewer: Literal['mock', 'anthropic', 'openai'] = 'mock'
    generator_model: str | None = None
    reviewer_model: str | None = None
    factual_mode: Literal['strict', 'model_reviewed'] = 'strict'
    max_revisions: int = Field(default=2, ge=0, le=3)
    max_calls: int = Field(default=48, ge=1, le=100)
    token_budget: int = Field(default=250000, ge=1000)
    max_output_tokens: int = Field(default=6000, ge=256, le=16000)
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def support_mode(self):
        self.generator_model = self.generator_model or DEFAULT_MODELS[self.generator]
        self.reviewer_model = self.reviewer_model or DEFAULT_MODELS[self.reviewer]
        if self.factual_mode == 'model_reviewed' and self.reviewer not in ('anthropic', 'openai'):
            raise ValueError('Reviewed paraphrases require a live reviewer, never mock approval')
        return self


class SupportQuote(BaseModel):
    evidence_id: str
    text: str = Field(min_length=1)


class ClaimAssessment(BaseModel):
    claim_id: str
    evidence_ids: list[str] = Field(min_length=1)
    quotes: list[SupportQuote] = Field(min_length=1)
    wording_supported: bool
    metrics_consistent: bool
    technology_consistent: bool
    scope_consistent: bool
    dates_titles_consistent: bool
