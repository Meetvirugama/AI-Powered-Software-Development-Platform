"""
OutputValidator — skeleton for Day 1.
Owner: Dev — W1

Day 1: stub with docstrings and type signatures (interface contract).
Day 2: validate() and repair() fully implemented.
Day 3: GroundingValidator added.

Usage (Day 2+)::

    validator = OutputValidator(llm_gateway=gateway)
    instance, ok = validator.validate(raw_json, RepositoryAnswer)
    if not ok:
        instance = await validator.repair(raw_json, RepositoryAnswer, error_detail)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from ai.llm.client import LLMGateway


class OutputValidator:
    """
    Validates and repairs LLM output against a Pydantic schema.

    Two-step process:
    1. ``validate()`` — parse JSON + Pydantic validate. Returns (instance, True) or (None, False).
    2. ``repair()``  — if validate fails, calls LLM to fix the JSON. Max 2 repair attempts.

    Args:
        llm_gateway: The LLMGateway used to call the repair LLM.
                     Only needed for repair(); validate() works without it.
    """

    def __init__(self, llm_gateway: "LLMGateway | None" = None) -> None:
        self._gateway = llm_gateway

    def validate(
        self,
        raw: str,
        schema: type[BaseModel],
    ) -> tuple[BaseModel | None, bool]:
        """
        Parse ``raw`` as JSON and validate against ``schema``.

        Args:
            raw:    Raw string from the LLM (should be JSON).
            schema: Pydantic model class to validate against.

        Returns:
            ``(model_instance, True)`` on success.
            ``(None, False)`` on any failure (JSON parse error or schema mismatch).

        Note:
            Does NOT raise — always returns a tuple. Callers check the bool flag.
        """
        # Day 2: implement
        raise NotImplementedError("OutputValidator.validate() implemented on Day 2.")

    async def repair(
        self,
        raw: str,
        schema: type[BaseModel],
        error: str,
    ) -> BaseModel:
        """
        Ask the LLM to fix a JSON string that failed schema validation.

        Repair prompt:
            "Fix this JSON to match the schema. Error: {error}\\nJSON: {raw}"

        Retry limit: 2 attempts. If both fail, raises ``LLMValidationError``.

        Args:
            raw:    The invalid JSON string from the first LLM call.
            schema: Pydantic model class the JSON should conform to.
            error:  The validation error detail string.

        Returns:
            A valid, validated ``schema`` instance.

        Raises:
            LLMValidationError: If the LLM cannot produce valid JSON within 2 attempts.
        """
        # Day 2: implement
        raise NotImplementedError("OutputValidator.repair() implemented on Day 2.")
