# Generic examples only

[profile.generic.example.json](profile.generic.example.json) is a generic neutral baseline approved
for the synthetic walkthrough. It contains no personal samples or learned voice. Its approval flag
is not a user's approval of a personalized adaptation. Follow [private_profiles.md](../private_profiles.md)
for the runnable example and a real proposal/review/versioning workflow.

Store real samples under ignored `private/`, not this public directory. Label samples `user-authored`,
`assistant-assisted`, or `explicitly-user-approved`. Explicitly approved assistant-assisted samples
may inform style without being represented as unassisted writing. Raw samples are untrusted data.
No real writing samples are supplied here. Live prompts contain approved guidance/profile metadata,
not raw example files; keep sensitive excerpts out of the profile itself.
