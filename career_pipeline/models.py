from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Source(BaseModel):
    reference: str
    status: Literal['user_confirmed', 'uncertain']

class Technology(BaseModel):
    name: str
    usage: str

class Metric(BaseModel):
    value: float = Field(allow_inf_nan=False)
    unit: str
    qualifier: Literal['realized', 'estimated', 'expected']

class Evidence(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]+$')
    employer: str
    official_title: str
    resume_display_title: str | None = Field(default=None, min_length=1)
    resume_display_title_approved: bool = False
    start: date
    end: date | None = None
    project: str
    actions: list[str]
    ownership: Literal['owned', 'contributed', 'familiarity']
    technologies: list[Technology]
    outcomes: list[str] = []
    metrics: list[Metric] = []
    sources: list[Source] = Field(min_length=1)
    approved_wording: list[str] = Field(min_length=1)
    prohibited_inferences: list[str] = []
    tags: list[str] = []

    @model_validator(mode='after')
    def dates(self):
        if self.resume_display_title and not self.resume_display_title_approved:
            raise ValueError('Descriptive resume title requires explicit user approval')
        if self.end and self.end < self.start:
            raise ValueError('employment end precedes start')
        return self

    @property
    def eligible(self):
        return all(s.status == 'user_confirmed' for s in self.sources)

class Career(BaseModel):
    display_name: str
    evidence: list[Evidence]

    @model_validator(mode='after')
    def unique(self):
        if len({e.id for e in self.evidence}) != len(self.evidence):
            raise ValueError('duplicate evidence ID')
        dates = {}
        for e in self.evidence:
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

class Finding(BaseModel):
    role: Literal['evidence', 'recruiter', 'voice']
    claim_id: str | None = None
    requirement_id: str | None = None
    evidence_ids: list[str] = []
    severity: Literal['error', 'suggestion', 'gap']
    message: str

class Settings(BaseModel):
    generator: Literal['mock', 'anthropic'] = 'mock'
    reviewer: Literal['mock', 'anthropic'] = 'mock'
    generator_model: str = 'claude-sonnet-4-5'
    reviewer_model: str = 'claude-sonnet-4-5'
    max_revisions: int = Field(default=2, ge=0, le=3)
    max_calls: int = Field(default=24, ge=1, le=50)
    token_budget: int = Field(default=100000, ge=1000)
    max_output_tokens: int = Field(default=3000, ge=256, le=8000)
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)
