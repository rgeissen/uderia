"""
Extension Runner: Executes extensions serially, passing context through the chain.

Each extension in the chain receives:
  - The original LLM answer context
  - Results from all prior extensions (for serial chaining)

LLMExtension instances automatically receive LLM config injection
before execute() and have their tokens extracted after execute().

Extensions never break the main answer — errors are caught per-extension
and recorded as ExtensionResult(success=False).
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from trusted_data_agent.extensions.base import Extension, LLMExtension
from trusted_data_agent.extensions.manager import ExtensionManager
from trusted_data_agent.extensions.models import ExtensionContext, ExtensionResult

logger = logging.getLogger("quart.app")


class ExtensionRunner:
    """
    Orchestrates serial execution of post-processing extensions.

    Usage:
        runner = ExtensionRunner(get_extension_manager())
        results = await runner.run(
            extension_specs=[{"name": "json"}, {"name": "decision", "param": "critical"}],
            context=extension_context,
            event_handler=sse_event_handler,
        )
    """

    def __init__(self, manager: ExtensionManager):
        self.manager = manager

    async def run(
        self,
        extension_specs: List[Dict[str, Any]],
        context: ExtensionContext,
        event_handler: Optional[Callable] = None,
    ) -> Dict[str, ExtensionResult]:
        """
        Execute extensions serially.

        Each extension receives the full context plus results from all
        prior extensions in context.previous_extension_results.

        Args:
            extension_specs: List of {"name": str, "param": str|None} dicts,
                             in the order they were specified in the query.
            context:         Rich context built from the LLM answer.
            event_handler:   Optional async callback for SSE event emission.

        Returns:
            Ordered dict mapping extension name → ExtensionResult.
        """
        results: Dict[str, ExtensionResult] = {}

        for spec in extension_specs:
            name = spec.get("name", "")          # activation_name (result key)
            ext_id = spec.get("extension_id", name)  # actual extension to look up
            param = spec.get("param")

            ext = self.manager.get_extension(ext_id)

            # --- Extension not found ---
            if ext is None:
                logger.warning(f"Extension '{ext_id}' (activation '{name}') not found — skipping")
                results[name] = ExtensionResult(
                    extension_name=name,
                    content=None,
                    content_type="text/plain",
                    success=False,
                    error=f"Extension '{ext_id}' not found",
                )
                continue

            # --- Parameter validation ---
            valid, error_msg = ext.validate_param(param)
            if not valid:
                logger.warning(f"Extension '{name}' param validation failed: {error_msg}")
                results[name] = ExtensionResult(
                    extension_name=name,
                    content=None,
                    content_type="text/plain",
                    success=False,
                    error=error_msg or f"Invalid parameter: {param}",
                )
                continue

            # --- Inject chain context ---
            context.previous_extension_results = dict(results)

            # --- Emit start event ---
            if event_handler:
                try:
                    await event_handler(
                        {
                            "type": "extension_start",
                            "payload": {"name": name, "param": param},
                        },
                        "notification",
                    )
                except Exception:
                    pass  # Don't let event emission break execution

            # --- LLM config injection for LLMExtension ---
            if isinstance(ext, LLMExtension) and getattr(ext, 'requires_llm', False):
                ext._user_uuid = context.user_uuid
                ext._llm_config_id = context.llm_config_id
                ext._provider = context.provider
                ext._model = context.model
                # Reset accumulators for this execution
                ext._total_input_tokens = 0
                ext._total_output_tokens = 0
                ext._total_cost_usd = 0.0

                if not context.llm_config_id:
                    logger.warning(
                        f"Extension '{name}' requires LLM but no llm_config_id "
                        "in context. Extension may fail."
                    )

            # --- Execute ---
            start_time = time.monotonic()
            try:
                result = await ext.execute(context, param)
                elapsed_ms = round((time.monotonic() - start_time) * 1000)
                result.metadata["execution_time_ms"] = elapsed_ms
                result.output_target = ext.output_target.value

                # --- Extract LLM tokens from LLMExtension ---
                if isinstance(ext, LLMExtension):
                    result.extension_input_tokens = ext._total_input_tokens
                    result.extension_output_tokens = ext._total_output_tokens
                    result.extension_cost_usd = ext._total_cost_usd
                    if ext._total_input_tokens > 0:
                        logger.info(
                            f"Extension '{name}' LLM usage: "
                            f"{ext._total_input_tokens} in / {ext._total_output_tokens} out "
                            f"(${ext._total_cost_usd:.6f})"
                        )

                results[name] = result
                logger.info(
                    f"Extension '{name}' completed in {elapsed_ms}ms "
                    f"(success={result.success})"
                )
            except Exception as e:
                elapsed_ms = round((time.monotonic() - start_time) * 1000)
                logger.error(f"Extension '{name}' raised exception: {e}", exc_info=True)
                results[name] = ExtensionResult(
                    extension_name=name,
                    content=None,
                    content_type="text/plain",
                    success=False,
                    error=str(e),
                    metadata={"execution_time_ms": elapsed_ms},
                )

            # --- Emit complete event ---
            if event_handler:
                try:
                    r = results[name]
                    complete_payload = {
                        "name": name,
                        "success": r.success,
                        "content_type": r.content_type,
                        "output_target": ext.output_target.value,
                        "execution_time_ms": r.metadata.get("execution_time_ms", 0),
                    }
                    # Include token/cost data for LLM extensions
                    if r.extension_input_tokens > 0 or r.extension_output_tokens > 0:
                        complete_payload["input_tokens"] = r.extension_input_tokens
                        complete_payload["output_tokens"] = r.extension_output_tokens
                        complete_payload["cost_usd"] = r.extension_cost_usd
                    await event_handler(
                        {
                            "type": "extension_complete",
                            "payload": complete_payload,
                        },
                        "notification",
                    )
                except Exception:
                    pass

        return results


def serialize_extension_results(
    results: Dict[str, ExtensionResult],
) -> Dict[str, Any]:
    """
    Serialize extension results for JSON transport (SSE events, task status, session storage).

    Returns a dict keyed by extension name with serializable values.
    """
    serialized = {}
    for name, result in results.items():
        serialized[name] = {
            "extension_name": result.extension_name,
            "content": result.content,
            "content_type": result.content_type,
            "success": result.success,
            "error": result.error,
            "output_target": result.output_target,
            "metadata": result.metadata,
            "extension_input_tokens": result.extension_input_tokens,
            "extension_output_tokens": result.extension_output_tokens,
            "extension_cost_usd": result.extension_cost_usd,
        }
    return serialized
