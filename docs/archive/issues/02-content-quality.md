# Check document quality separately from factual accuracy

Problem: accurate statements can still produce a fragmented, incomplete or poorly ordered application.

Acceptance:
- Flag repeated/fragmented bullets, unexplained scientific notation and letters consisting of disconnected metrics.
- Detect omitted selected publications/education/skills and accidental cross-employer headings.
- Check reverse chronology and preserve official versus approved descriptive title distinctions.
- Presentation thresholds are configurable warnings; factual errors still block final export.
- Synthetic regressions reproduce the observed weak resume/letter without including private career facts.
- Human preference/editing effort is recorded only when actually supplied.

Reference: career-ops verify-cv-structure.mjs, alongside its separate factual gate (MIT).

Implementation on `feat/content-quality-checks`:
- Added configurable, nonblocking presentation checks for short/ledger bullets, repeated passages,
  scientific notation, role chronology, cross-employer scope, disconnected ledger-like letters,
  and omitted selected skills categories. Existing selected education/publication checks remain.
- Findings survive evidence-auditor revalidation and feed the bounded revision loop in live mode.
- Practice runs explicitly do not assess writing quality. Reports show whether checks ran.
- Synthetic regressions distinguish a factual pass with writing warnings from an unsupported
  claim that still blocks approval. These heuristics do not prove overall writing quality;
  human preference and rendered-page assessment remain separate work.
