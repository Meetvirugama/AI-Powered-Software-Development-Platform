
import unittest

from agent.tools.router import ToolDefinition, ToolRequest, ToolRouter


class TestToolRouter(unittest.TestCase):
    def setUp(self):
        self.router = ToolRouter()

    def test_unknown_tool_is_rejected(self):
        result = self.router.route(
            ToolRequest(tool_name="missing_tool"),
            agent_state=None,
        )
        self.assertFalse(result.success)
        self.assertIn("Unknown tool", result.error)

    def test_registered_tool_is_not_executed_yet(self):
        executed = []
        definition = ToolDefinition(
            name="example",
            description="Example test tool",
            parameters={"type": "object", "properties": {}},
        )
        self.router.register(
            definition,
            lambda **kwargs: executed.append(kwargs),
        )

        result = self.router.route(
            ToolRequest(tool_name="example"),
            agent_state=None,
        )

        self.assertFalse(result.success)
        self.assertIn("policy checks", result.error)
        self.assertEqual(executed, [])

    def test_missing_required_argument_is_rejected(self):
        self.router.register(
            ToolDefinition(
                name="example",
                description="Example tool",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            lambda **kwargs: kwargs,
        )

        result = self.router.route(
            ToolRequest(tool_name="example", arguments={}),
            agent_state=None,
        )

        self.assertFalse(result.success)
        self.assertIn("Missing required argument", result.error)

    def test_wrong_argument_type_is_rejected(self):
        self.router.register(
            ToolDefinition(
                name="example",
                description="Example tool",
                parameters={
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                    "required": ["count"],
                },
            ),
            lambda **kwargs: kwargs,
        )

        result = self.router.route(
            ToolRequest(
                tool_name="example",
                arguments={"count": "five"},
            ),
            agent_state=None,
        )

        self.assertFalse(result.success)
        self.assertIn("must be of type integer", result.error)

    def test_unexpected_argument_is_rejected(self):
        self.router.register(
            ToolDefinition(
                name="example",
                description="Example tool",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "additionalProperties": False,
                },
            ),
            lambda **kwargs: kwargs,
        )

        result = self.router.route(
            ToolRequest(
                tool_name="example",
                arguments={"path": "src/main.py", "admin": True},
            ),
            agent_state=None,
        )

        self.assertFalse(result.success)
        self.assertIn("Unexpected argument", result.error)


if __name__ == "__main__":
    unittest.main()
