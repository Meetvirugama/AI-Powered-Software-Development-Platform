
import unittest

from agent.tools.router import (
    ToolDefinition,
    ToolRequest,
    ToolRouter,
)


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


if __name__ == "__main__":
    unittest.main()
