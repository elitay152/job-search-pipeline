# Calibration

See [Private, approved writing profiles](private_profiles.md) for the complete workflow, a generic
credential-free walkthrough, provider-transmission boundaries and private backup guidance.

1. Select professional or academic samples separately from conversational style. Keep originals
   and UTF-8 plain-text extracts under ignored `private/` and label authorship honestly.
2. Run `career calibrate --samples private/samples.json --output private/profile-proposal.json`.
   The manifest is a list of `{id, path, authorship}`. Accepted labels are `user-authored` and
   `explicitly-user-approved`; assistant-assisted samples require explicit user approval to qualify.
   The CLI reads text, not DOCX/PDF. It performs only local sentence-length analysis and proposes
   neutral guidance; no raw samples are sent to a model or treated as instructions.
3. Inspect the observations, edit the application guidance and compare short before/after examples.
   Academic conventions need not become application preferences. Do not infer personality.
4. Approval of samples is separate from approval of the derived profile. After explicit user approval,
   create a new versioned private package containing SKILL.md, profile.json, resume_guidance.md,
   SOURCES.md and licenses/. Set approved=true and a distinct profile version only for that package.
5. Pass `--style private/writing_style/approved-v1` explicitly for personal CLI runs. The Python
   equivalent is `style_path=...`. The UI currently uses the public neutral default. An active-profile
   note does not select a profile automatically. Each run stores version, instructions and bundle hash.
6. Preserve prior packages and approval notes. Back up private files separately; Git ignores them.

The portable package is explicitly loaded by this application, not auto-discovered by Claude Code.
