# Public resume skill research

Reviewed public GitHub sources on 2026-10-24. This is source inspection, not an execution or quality benchmark.
No external skill was installed, executed, or given personal documents. External instructions were treated as
reference material, not project policy. GitHub public search worked; skills.sh and GitHub API requests were blocked.

| Source | Useful guidance | Adaptation required |
|---|---|---|
| [Paramchoudhary/ResumeSkills](https://github.com/Paramchoudhary/ResumeSkills), `resume-formatter`, `tech-resume-optimizer`, `resume-bullet-writer` | Simple single-column documents, standard headings, visual hierarchy, readable technical accomplishments | Bullet guidance includes estimates; only use metrics the user confirms. Keyword-match scores are heuristics, not validated ATS behavior or hiring probabilities. |
| [varunr89/resume-tailoring-skill](https://github.com/varunr89/resume-tailoring-skill) | Multiple-resume library, requirement-driven selection, structured discovery questions, stated factual-integrity goal | Its title-reframing and combined-title suggestions conflict with preserving official titles. Do not adopt those rules. Company/profile research and batch workflows exceed current MVP scope. |
| [proficientlyjobs/proficiently-claude-skills](https://github.com/proficientlyjobs/proficiently-claude-skills), `tailor-resume` | Explicit no-invention rules, preserve titles/dates, requirement mapping, factual correction persistence, concise writing critique | Browser dependencies and promotional footer are unnecessary here. A Flesch score above 90 is not an appropriate mandatory target for technical resumes. No root license file was found during inspection; verify reuse permissions before copying. |
| [anthropics/skills](https://github.com/anthropics/skills/tree/main/skills/docx), `docx` | Word formatting details, render-and-inspect output validation | Document tooling, not resume strategy. Skill declares proprietary terms. Python project need not adopt its JavaScript implementation. Review license before reuse. |

Recommendation: adapt formatting and technical-bullet review ideas into a small project-specific guide,
keeping confirmed facts, official titles, metric qualifiers, ownership, provenance and bounded review as higher-priority rules.
Do not import an entire collection or replace the evidence pipeline. Inspect licensing and source instructions
before copying material. Evaluate any adapted guidance against synthetic adversarial fixtures and user-reviewed
output. No ATS compatibility, interview likelihood, or quality improvement has been established by this search.

Inspected revisions:

- ResumeSkills: `74ae19e7c62b0516d1c298328e5544976c12da5d` (root MIT license).
- resume-tailoring-skill: `9a4a0f20f5983d1b533627b8c5191acd1ca0cd89` (root MIT license).
- proficiently-claude-skills: `9bc1f6fd7af532fe0cd4a1843e06ab2b474d0d53`.
- anthropics/skills: `dbd4588f9e1033efb41dad4bef2f7947c8993d44`.

## Adaptation decision

User selected ResumeSkills and resume-tailoring-skill only. Adapted guidance is in
writing_style/resume_guidance.md with source attribution and MIT notices. Proficiently and
Anthropic DOCX remain research references only and are excluded from implementation.
User-approved descriptive titles are supported separately from official employment titles.
