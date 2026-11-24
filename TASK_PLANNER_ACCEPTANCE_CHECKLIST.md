# Acceptance checklist

- [x] A user can submit a development prompt from Repository Task Studio.
- [x] Prompt intake checks repository ownership and distinguishes tested ambiguous prompts.
- [x] Plan approval is explicit and bound to the persisted plan version.
- [x] The local end-to-end fixture exercises multi-file edits, pytest, bounded repair and an exact verified commit.
- [x] Branch publication requires a separate actor-bound approval for that SHA.
- [x] A failed Draft PR request can be retried without recording a fabricated PR.
- [x] The frontend passes its tests and production build.
- [x] Deployment changes required for the remote runner are documented.
- [x] A clean local PostgreSQL database accepts the migrations and passes the task lifecycle fixture. A temporary Redis instance responds to its health check.
- [ ] Validate GitHub App repository checkout, authenticated push and live Draft PR creation.
- [ ] Validate the shared workspace mount with the actual Azure API and isolated runner.
- [ ] Validate PostgreSQL and Redis durability and restart recovery in a representative environment.
- [ ] Evaluate correctness across repositories and supported languages, including dependency installation, test selection and repair.
- [ ] Resolve the 12 failures in the full backend regression suite.
- [ ] Complete GitHub publication of this implementation branch and confirm its Draft PR.
