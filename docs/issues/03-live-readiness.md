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
