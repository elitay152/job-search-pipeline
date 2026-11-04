# Make provider readiness and application states explicit

Problem: a generic ValueError and practice output looked like a usable live application.

Acceptance:
- Show app version and key presence without exposing secrets.
- Offer a synthetic connection/model test before sending personal data.
- Explain budget reservations before requests and expose safe, actionable failure reasons.
- Practice mode, generating, needs review, approved and final export have distinct UI states.
- Approval always refreshes final downloads; stale drafts cannot appear as final files.
- Verify the Windows setup path and distinguish actual Windows tests from Linux checks.

Already merged: adaptive retry budget, missing-key diagnostics, practice warning and approval download refresh.

Follow-up diagnostics implementation: known review-contract failures, incomplete tool results,
schema-invalid data, budgets and provider errors now have allowlisted explanations. Failed runs
persist their active stage and safe diagnostic; the UI offers a content-free diagnostic download.
The output-token limit is exposed independently of the total budget. These diagnostics do not
claim to resolve an unidentified local failure or replace a synthetic connection test.
