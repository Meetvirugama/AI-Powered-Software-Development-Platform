import { describe, it, expect, vi } from 'vitest';
import {
  buildExplanationMarkdown,
  explanationExportFileName,
  downloadExplanationMarkdown,
} from '../lib/explanationMarkdown';
import type { CodeExplanation } from '../types/analysis';

describe('explanationMarkdown (Module 7 Analysis Export)', () => {
  const sampleExplanation: CodeExplanation = {
    purpose: 'Handles authentication and JWT token issuance.',
    detailed_explanation: 'Validates user credentials against password hash, checks lockouts, and signs token.',
    logic_flow: ['Receive credentials', 'Query user by email', 'Compare argon2 hash', 'Return JWT'],
    execution_flow: ['Client calls POST /api/login', 'Router forwards to auth service', 'Database queried'],
    inputs_and_outputs: 'Input: credentials object. Output: auth token or 401 error.',
    code_output_explanation: 'Returns a signed JWT bearer string with 15-minute expiry.',
    key_symbols: [
      { name: 'authenticate_user', kind: 'function', start_line: 12, end_line: 45, role: 'Authenticates credentials' },
    ],
    dependencies: ['argon2', 'jwt', 'sqlalchemy'],
    related_files: ['backend/app/core/security.py', 'backend/app/models/user.py'],
    call_graph_depth_expanded: true,
    expanded_callers: ['api_v1_login (L30)'],
    expanded_callees: ['verify_password (L88)', 'create_access_token (L120)'],
    code_issues_and_solutions: ['Potential timing attack on user existence -> Use constant-time dummy verification'],
    corrected_code: 'def authenticate_user():\n    # corrected constant time\n    pass',
    assumptions_and_limitations: ['Assumes PostgreSQL connection pool is initialized.'],
    missing_context: ['External SSO provider configs not loaded.'],
    sources: [{ file_path: 'backend/app/services/auth.py', start_line: 12, end_line: 45, symbol_name: 'authenticate_user' }],
    confidence: 'high',
    has_redacted_content: true,
    redacted_occurrences: 2,
    redaction_notice: 'Source contained 2 redacted secret values.',
  };

  it('builds a comprehensive markdown document with all fields and headings', () => {
    const md = buildExplanationMarkdown(sampleExplanation, {
      targetFilePath: 'backend/app/services/auth.py',
      generatedAt: '2026-11-20T12:00:00Z',
    });

    expect(md).toContain('# Code Explanation: `backend/app/services/auth.py`');
    expect(md).toContain('- **Confidence:** high');
    expect(md).toContain('- **Generated:** 2026-11-20T12:00:00Z');
    expect(md).toContain('## Security Notice');
    expect(md).toContain('Source contained 2 redacted secret values.');
    expect(md).toContain('## Purpose\n\nHandles authentication and JWT token issuance.');
    expect(md).toContain('## Detailed Explanation');
    expect(md).toContain('## Logic Flow\n\n1. Receive credentials\n2. Query user by email\n3. Compare argon2 hash\n4. Return JWT');
    expect(md).toContain('## Execution Flow');
    expect(md).toContain('## Inputs and Outputs');
    expect(md).toContain('## Output Explanation');
    expect(md).toContain('## Key Symbols');
    expect(md).toContain('- `authenticate_user` *function* (L12-L45) — Authenticates credentials');
    expect(md).toContain('## Dependencies\n\n- argon2\n- jwt\n- sqlalchemy');
    expect(md).toContain('## Related Files\n\n- `backend/app/core/security.py`\n- `backend/app/models/user.py`');
    expect(md).toContain('## Expanded Call Graph');
    expect(md).toContain('**Callers**\n- api_v1_login (L30)');
    expect(md).toContain('**Callees**\n- verify_password (L88)\n- create_access_token (L120)');
    expect(md).toContain('## Issues and Solutions');
    expect(md).toContain('## Corrected Code\n\n```python\ndef authenticate_user():\n    # corrected constant time\n    pass\n```');
    expect(md).toContain('## Assumptions and Limitations');
    expect(md).toContain('## Missing Context');
    expect(md).toContain('## Sources\n\n- `backend/app/services/auth.py:L12-L45` (`authenticate_user`)');
  });

  it('generates a clean slugified export filename', () => {
    expect(explanationExportFileName('backend/app/services/auth.py')).toBe('explanation-backend-app-services-auth-py.md');
    expect(explanationExportFileName(undefined)).toBe('explanation-code.md');
    expect(explanationExportFileName('a/b/c/long-path-name.ts')).toBe('explanation-a-b-c-long-path-name-ts.md');
  });

  it('triggers a browser file download via anchor element click', () => {
    const createObjectURLMock = vi.fn().mockReturnValue('blob:mock-url');
    const revokeObjectURLMock = vi.fn();
    window.URL.createObjectURL = createObjectURLMock;
    window.URL.revokeObjectURL = revokeObjectURLMock;

    const clickMock = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      const el = originalCreateElement(tagName);
      if (tagName === 'a') {
        el.click = clickMock;
      }
      return el;
    });

    downloadExplanationMarkdown(sampleExplanation, 'src/test.py');

    expect(createObjectURLMock).toHaveBeenCalled();
    expect(clickMock).toHaveBeenCalled();
  });
});
