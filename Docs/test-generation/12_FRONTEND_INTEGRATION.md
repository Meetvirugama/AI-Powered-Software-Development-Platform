# Frontend Integration: TestGenerationView.tsx

---

## 1. Component Enhancements

The frontend test studio component (`frontend/src/components/explorer/TestGenerationView.tsx`) was upgraded to present full verification telemetry:

1. **Top Banner: Verification Pipeline Status**:
   - `VERIFIED` (emerald): Shows "VERIFIED (Passed static checks, 3/3 stability runs, and attributed coverage)".
   - `UNVERIFIED` (amber): Highlights unverified or failing criteria.
   - `REJECTED` (rose): Indicates path/conftest violations or dangerous tokens.
   - `EXECUTION_ERROR` (zinc): Indicates sandbox or infrastructure failures.
   - Displays exact remediation/verification reasons from backend.

2. **Stability Validation Card**:
   - Displays passed runs over total (`3/3 PASSED (STABLE)`).
   - Per-run cards display duration in seconds, exit code, and error messages.

3. **Runtime Coverage Attribution Card**:
   - Grid showing: Baseline Line Cov, Final Line Cov, Line Gain (+X.X%), and New Lines Covered.
   - Attributed pill badge confirming generated test contribution.
   - List of newly exercised source lines.

4. **Iterative Rounds Card**:
   - Displays total iteration rounds conducted (`X/3`) and stopping reason.

5. **Sandboxed Execution Terminal Output**:
   - Collapsible terminal viewer rendering `raw_execution_output` with secret redaction.

6. **Preserved Workflows**:
   - One-click copy, download, framework command copying, and quality scorecard metrics remain fully functional.
