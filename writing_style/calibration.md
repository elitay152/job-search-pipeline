# Calibration
1. Select professional samples and record authorship labels; exclude conversational samples.
2. Run `career calibrate --samples private/samples.json --output private/profile-proposal.json`.
   The manifest is a list of {id, path, authorship}. This local operation measures sentence length,
   does not send raw samples to a model, and proposes guidance without asserting personality.
3. Review the proposal's short before/after illustration and sample IDs. Edit all guidance.
4. Copy SKILL.md into a private style directory, save the edited proposal as profile.json,
   set approved=true and give it a new version after your explicit review.
5. Pass `--style private/style` for future runs. A run stores profile version and hash.
The portable package is explicitly loaded by this application, not auto-discovered by Claude Code.
