"""
OutputValidator — validates and repairs LLM structured output.
Owner: Dev — W1

Day 1: stub with interface contract.
Day 2: full implementation — validate() + repair() with 2-retry limit.
Day 3: GroundingValidator added (separate class, same file).

Usage::

    validator = OutputValidator(llm_gateway=gateway)

    # Try to validate first
    instance, ok = validator.validate(raw_json, RepositoryAnswer)
    if not ok:
        # Ask the LLM to fix its own output
        instance = await validator.repair(raw_json, RepositoryAnswer, error_detail)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from ai.llm.client import LLMGateway

logger = logging.getLogger(__name__)

# Maximum number of repair attempts before giving up
_MAX_REPAIR_ATTEMPTS = 2


class OutputValidator:
    """
    Validates and repairs LLM output against a Pydantic schema.

    Two-step process:
    1. ``validate()`` — parse JSON + Pydantic validate.
       Returns ``(instance, True)`` on success, ``(None, False)`` on failure.
    2. ``repair()``  — if validate fails, calls LLM to fix the JSON.
       Max 2 repair attempts before raising LLMValidationError.

    Args:
        llm_gateway: The LLMGateway used for repair LLM calls.
                     Optional — only needed if ``repair()`` will be called.
    """

    def __init__(self, llm_gateway: "LLMGateway | None" = None) -> None:
        self._gateway = llm_gateway

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        raw: str,
        schema: type[BaseModel],
    ) -> tuple[BaseModel | None, bool]:
        """
        Parse ``raw`` as JSON and validate against ``schema``.

        Args:
            raw:    Raw string from the LLM (should be valid JSON).
            schema: Pydantic model class to validate against.

        Returns:
            ``(model_instance, True)`` — valid JSON that matches the schema.
            ``(None, False)``          — any failure: bad JSON or schema mismatch.

        Note:
            This method never raises. Callers always check the bool flag.
        """
        try:
            parsed: Any = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug(
                "output_validation_failed",
                extra={"reason": "json_parse_error", "detail": str(exc)},
            )
            return None, False

        try:
            instance = schema.model_validate(parsed)
            logger.debug(
                "output_validation_passed",
                extra={"schema": schema.__name__},
            )
            return instance, True
        except ValidationError as exc:
            logger.debug(
                "output_validation_failed",
                extra={"reason": "schema_validation_error", "schema": schema.__name__, "detail": str(exc)},
            )
            return None, False

    async def repair(
        self,
        raw: str,
        schema: type[BaseModel],
        error: str,
    ) -> BaseModel:
        """
        Ask the LLM to fix a JSON string that failed schema validation.

        Repair prompt sent to the LLM::

            Fix this JSON so it matches the required schema.
            Schema: <schema name>
            Validation error: <error>
            Invalid JSON:
            <raw>

            Respond with ONLY the corrected JSON object.

        Retry limit: ``_MAX_REPAIR_ATTEMPTS`` (2). On each attempt:
        1. Call LLM with repair prompt.
        2. Run ``validate()`` on the LLM response.
        3. If valid, return the instance.
        4. If still invalid after all attempts, raise ``LLMValidationError``.

        Args:
            raw:    The invalid JSON string from the original LLM call.
            schema: Pydantic model class the JSON should conform to.
            error:  The validation error detail from the first validate() call.

        Returns:
            A valid, validated ``schema`` instance.

        Raises:
            LLMValidationError: If the LLM cannot produce valid JSON within
                                ``_MAX_REPAIR_ATTEMPTS`` attempts.
            RuntimeError:       If called without a configured ``llm_gateway``.
        """
        from ai.llm.schemas import LLMRequest, Message, LLMValidationError

        if self._gateway is None:
            raise RuntimeError(
                "OutputValidator.repair() requires an LLMGateway. "
                "Pass llm_gateway= when constructing OutputValidator."
            )

        current_raw = raw
        current_error = error

        for attempt in range(1, _MAX_REPAIR_ATTEMPTS + 1):
            repair_prompt = (
                f"Fix this JSON so it matches the required schema.\n"
                f"Schema: {schema.__name__}\n"
                f"Validation error: {current_error}\n"
                f"Invalid JSON:\n{current_raw}\n\n"
                f"Respond with ONLY the corrected JSON object. No explanation."
            )

            request = LLMRequest(
                model="gpt-4o",
                messages=[Message(role="user", content=repair_prompt)],
                temperature=0.0,
                max_tokens=1024,
            )

            try:
                response = await self._gateway.generate(request)
                repaired_raw = response.content

                instance, ok = self.validate(repaired_raw, schema)
                if ok:
                    logger.info(
                        "output_repair_succeeded",
                        extra={"schema": schema.__name__, "attempt": attempt},
                    )
                    return instance  # type: ignore[return-value]

                # Update for next iteration
                current_raw = repaired_raw
                current_error = f"Still invalid after repair attempt {attempt}."

            except Exception as exc:
                logger.warning(
                    "output_repair_llm_error",
                    extra={"attempt": attempt, "error": str(exc)},
                )
                current_error = str(exc)

        logger.error(
            "output_repair_failed",
            extra={"schema": schema.__name__, "attempts": _MAX_REPAIR_ATTEMPTS},
        )
        raise LLMValidationError(
            f"Could not repair LLM output for schema '{schema.__name__}' "
            f"after {_MAX_REPAIR_ATTEMPTS} attempts. Last error: {current_error}"
        )
