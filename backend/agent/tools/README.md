# Agent Tool Router

Policy-enforced tool routing, schema validation, command allowlisting, and output sanitization for agent task execution.

## Components

- **`ToolDefinition`**: Data model defining tool name, description, and JSON Schema parameters.
- **`ToolRequest`**: Agent request specifying `tool_name` and JSON argument payload.
- **`ToolResult`**: Execution envelope returning boolean `success`, sanitized `output`, and optional `error`.
- **`ToolRouter`**: Central router responsible for:
  - Tool registration and strict JSON Schema argument verification.
  - Command allowlist validation (`argv` token inspection, path traversal prevention, forbidden flags rejection).
  - Pre-flight `PolicyEngine` authorization checks.
  - Secret redaction (API keys, GitHub tokens, OpenAI keys) and bounded output truncation.

## Usage

```python
from agent.tools import ToolDefinition, ToolRequest, ToolRouter

router = ToolRouter(command_allowlist={"run_tests": [["pytest", "tests/"]]})
result = router.route(request, agent_state)
```

