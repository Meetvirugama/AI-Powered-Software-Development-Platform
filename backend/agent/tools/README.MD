
# Agent Tool Router — Interface Contract

## ToolDefinition
- `name`: Unique tool name.
- `description`: Human-readable description.
- `parameters`: JSON Schema describing the tool's arguments.

## ToolRequest
- `tool_name`: Name of the requested tool.
- `arguments`: Arguments supplied to the tool.

## ToolResult
- `success`: Whether the request succeeded.
- `output`: Tool output, if available.
- `error`: Error message, if the request failed.

## ToolRouter
- `register(definition, handler)`: Register a tool.
- `get_tools()`: List registered tool definitions.
- `route(request, agent_state)`: Route a tool request.

## Security boundary
Tool execution remains disabled until PolicyEngine authorization
and argument validation are integrated. Every tool must be authorized
before execution, and output must be sanitized before being returned.

## Integration dependencies
- AgentState: To be aligned with the orchestrator interface.
- PolicyEngine.check(): To be aligned with the security interface.
