# Troubleshooting Guide: Test Generation & Verification

---

## 1. Common Verification Issues & Remediation

### Issue 1: Test Result Shows `UNVERIFIED` (Flaky Candidate)
- **Symptom**: `verification_status` is `UNVERIFIED`, with message: `Test exhibited flakiness: passed 2/3 stability runs`.
- **Root Cause**: The generated test relies on non-deterministic data, race conditions, unpinned timestamps, or unmocked external network/random sources.
- **Remediation**: Inspect the failed run's error message in `raw_execution_output`. Ensure fixtures mock random generators, system clocks (`freezegun`), and external API calls.

### Issue 2: Test Result Shows `UNVERIFIED` (0% Coverage Gain)
- **Symptom**: `verification_status` is `UNVERIFIED`, with message: `Test executed cleanly across 3 runs, but produced 0% coverage gain on target file`.
- **Root Cause**: The test passed because it asserted trivial conditions (`assert True`) or tested code outside the specified target file.
- **Remediation**: Check `coverage_report.newly_covered_lines`. Ensure the prompt specifically targets uncovered lines and branch statements in the target module.

### Issue 3: Result Shows `EXECUTION_ERROR`
- **Symptom**: Status is `EXECUTION_ERROR`, with message: `Infrastructure error: Unable to provision isolated sandbox workspace`.
- **Root Cause**: Host filesystem permissions or disk quotas prevented directory creation under `.workspaces/`.
- **Remediation**: Check permissions on `.workspaces/` and ensure the filesystem has available inodes and free disk space.

### Issue 4: Result Shows `REJECTED`
- **Symptom**: Status is `REJECTED`, with warning about `conftest.py` or `.github/workflows`.
- **Root Cause**: The model proposed overwriting a reserved or auto-executed configuration file.
- **Remediation**: The orchestrator automatically falls back to convention-derived test paths (e.g. `tests/test_<module>.py`).
