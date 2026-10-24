# Verify rendered resume and cover-letter layout

Problem: correct DOCX text does not establish readable pagination or professional layout.

Acceptance:
- Render with an optional local dependency and explicitly report unavailable rendering.
- Inspect page count, orphaned headings, clipping, dense sections and letter overflow.
- Keep editable DOCX and Markdown available without PDF dependencies.
- Show the reviewed document version and bind approval/download to that version.
- Use synthetic fixtures and verify actual rendered artifacts when a renderer is available.

Reference: ai-job-search mandatory compile-and-inspect stage (MIT). Do not copy a fixed page-count
rule as a universal factual constraint; expose layout preferences separately.
