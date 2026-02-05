"""
Flow Executor - DAG-based flow execution engine.
Executes flows by calling Uderia REST API for profile nodes.
"""

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Set, Any, Optional

import httpx
from simpleeval import simple_eval

from flow_graph import FlowGraph, Node
from flow_manager import flow_manager

logger = logging.getLogger(__name__)


class FlowExecutionError(Exception):
    """Raised when flow execution fails."""
    pass


class FlowExecutor:
    """
    DAG-based flow execution engine.
    Executes flows by calling Uderia REST API for profile nodes.
    """

    def __init__(
        self,
        uderia_base_url: str,
        jwt_token: str,
        timeout: float = 300.0
    ):
        self.uderia_url = uderia_base_url.rstrip("/")
        self.jwt_token = jwt_token
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {jwt_token}"}
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
        return self._http_client

    async def close(self):
        """Close HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def execute_flow(
        self,
        flow_definition: dict,
        execution_id: str,
        initial_input: str
    ) -> AsyncGenerator[dict, None]:
        """
        Execute a flow with conditional branching.
        Yields events as the flow progresses.
        """
        # Build graph from definition
        graph = FlowGraph.from_definition(flow_definition)

        # Validate graph
        errors = graph.validate()
        if errors:
            yield {
                "event": "flow_execution_error",
                "error": f"Invalid flow: {'; '.join(errors)}"
            }
            return

        yield {
            "event": "flow_execution_start",
            "execution_id": execution_id,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges)
        }

        # Track execution state
        node_results: Dict[str, Any] = {}
        completed: Set[str] = set()
        running: Set[str] = set()
        skipped: Set[str] = set()
        uderia_sessions: List[str] = []
        total_tokens = {"input": 0, "output": 0}

        # Initialize context with initial input
        context = {"initial_input": initial_input, "query": initial_input}

        # Get starting nodes
        start_nodes = graph.get_starting_nodes()
        pending = deque(start_nodes)

        try:
            while pending:
                node_id = pending.popleft()

                # Skip if already processed
                if node_id in completed or node_id in skipped:
                    continue

                node = graph.get_node(node_id)
                if not node:
                    continue

                # Check dependencies
                if not graph.dependencies_met(node_id, completed):
                    # Re-add to queue if dependencies not met
                    pending.append(node_id)
                    continue

                # Mark as running
                running.add(node_id)

                # Emit node started event
                yield {
                    "event": "flow_node_started",
                    "node_id": node_id,
                    "node_type": node.type,
                    "node_label": node.label
                }

                # Record node execution start
                node_exec = await flow_manager.create_node_execution(
                    execution_id=execution_id,
                    node_id=node_id,
                    node_type=node.type,
                    node_label=node.label,
                    input_data=self._get_node_input(node, context, node_results)
                )

                start_time = time.time()

                try:
                    # Execute the node
                    result = await self._execute_node(
                        node=node,
                        context=context,
                        node_results=node_results,
                        execution_id=execution_id,
                        uderia_sessions=uderia_sessions,
                        event_callback=lambda e: None  # TODO: yield events
                    )

                    duration_ms = int((time.time() - start_time) * 1000)

                    # Store result
                    node_results[node_id] = result
                    completed.add(node_id)
                    running.discard(node_id)

                    # Update context with result
                    context["previous"] = result
                    context[f"node_{node_id}"] = result

                    # Track tokens
                    if "tokens" in result:
                        total_tokens["input"] += result["tokens"].get("input", 0)
                        total_tokens["output"] += result["tokens"].get("output", 0)

                    # Update node execution record
                    await flow_manager.update_node_execution(
                        node_exec_id=node_exec["id"],
                        status="completed",
                        output=result,
                        duration_ms=duration_ms
                    )

                    # Emit node completed event
                    yield {
                        "event": "flow_node_completed",
                        "node_id": node_id,
                        "node_type": node.type,
                        "node_label": node.label,
                        "duration_ms": duration_ms,
                        "result_summary": self._summarize_result(result)
                    }

                    # Evaluate outgoing edges and add next nodes
                    next_nodes = graph.evaluate_edges(node_id, result)
                    for next_id in next_nodes:
                        if next_id not in completed and next_id not in pending:
                            pending.append(next_id)

                    # For condition nodes, mark skipped branches
                    if node.type == "condition":
                        all_targets = graph.get_successors(node_id)
                        for target in all_targets:
                            if target not in next_nodes:
                                skipped.add(target)
                                yield {
                                    "event": "flow_node_skipped",
                                    "node_id": target,
                                    "reason": "condition_false"
                                }

                except Exception as e:
                    duration_ms = int((time.time() - start_time) * 1000)
                    running.discard(node_id)

                    # Update node execution record with error
                    await flow_manager.update_node_execution(
                        node_exec_id=node_exec["id"],
                        status="failed",
                        error_message=str(e),
                        duration_ms=duration_ms
                    )

                    yield {
                        "event": "flow_node_error",
                        "node_id": node_id,
                        "node_type": node.type,
                        "error": str(e)
                    }

                    raise FlowExecutionError(f"Node '{node_id}' failed: {e}")

            # Collect final results from end nodes
            end_nodes = graph.get_ending_nodes()
            final_results = []
            for end_id in end_nodes:
                if end_id in node_results:
                    final_results.append(node_results[end_id])

            # Merge final results
            final_result = self._merge_final_results(final_results)

            yield {
                "event": "flow_execution_complete",
                "execution_id": execution_id,
                "result": final_result,
                "token_usage": total_tokens,
                "nodes_executed": len(completed),
                "nodes_skipped": len(skipped)
            }

            # Update execution record
            await flow_manager.update_execution(
                execution_id=execution_id,
                status="completed",
                result=final_result,
                token_usage=total_tokens,
                uderia_sessions=uderia_sessions
            )

        except FlowExecutionError as e:
            await flow_manager.update_execution(
                execution_id=execution_id,
                status="failed",
                error_message=str(e),
                token_usage=total_tokens,
                uderia_sessions=uderia_sessions
            )
            yield {
                "event": "flow_execution_error",
                "execution_id": execution_id,
                "error": str(e)
            }

        except Exception as e:
            logger.exception(f"Unexpected error in flow execution: {e}")
            await flow_manager.update_execution(
                execution_id=execution_id,
                status="failed",
                error_message=f"Unexpected error: {e}",
                token_usage=total_tokens,
                uderia_sessions=uderia_sessions
            )
            yield {
                "event": "flow_execution_error",
                "execution_id": execution_id,
                "error": str(e)
            }

    async def _execute_node(
        self,
        node: Node,
        context: Dict[str, Any],
        node_results: Dict[str, Any],
        execution_id: str,
        uderia_sessions: List[str],
        event_callback
    ) -> Dict[str, Any]:
        """Execute a single node based on its type."""

        node_type = node.type
        data = node.data

        if node_type == "start":
            return await self._execute_start_node(data, context)

        elif node_type == "end":
            return await self._execute_end_node(data, context, node_results)

        elif node_type == "profile":
            return await self._execute_profile_node(data, context, uderia_sessions)

        elif node_type == "condition":
            return await self._execute_condition_node(data, context)

        elif node_type == "merge":
            return await self._execute_merge_node(data, context, node_results)

        elif node_type == "transform":
            return await self._execute_transform_node(data, context)

        elif node_type == "loop":
            return await self._execute_loop_node(data, context, node_results, execution_id, event_callback)

        elif node_type == "human":
            return await self._execute_human_node(data, context, execution_id, node.id)

        elif node_type == "parallel":
            # Parallel execution is handled at the graph level
            return {"status": "parallel_fork", "branches": []}

        else:
            raise FlowExecutionError(f"Unknown node type: {node_type}")

    async def _execute_start_node(self, data: dict, context: dict) -> dict:
        """Execute start node - pass through initial input."""
        input_var = data.get("inputVariable", "query")
        return {
            "result": context.get(input_var, context.get("initial_input")),
            "status": "success"
        }

    async def _execute_end_node(self, data: dict, context: dict, node_results: dict) -> dict:
        """Execute end node - format final output."""
        output_format = data.get("outputFormat", "raw")
        include_metadata = data.get("includeMetadata", False)

        result = context.get("previous", {})

        if output_format == "json":
            return {"result": result, "format": "json"}
        elif output_format == "markdown":
            # Convert to markdown if possible
            if isinstance(result, dict) and "result" in result:
                return {"result": str(result["result"]), "format": "markdown"}
            return {"result": str(result), "format": "markdown"}
        else:
            return {"result": result, "format": "raw"}

    async def _execute_profile_node(
        self,
        data: dict,
        context: dict,
        uderia_sessions: List[str]
    ) -> dict:
        """Execute a profile node via Uderia REST API."""
        profile_id = data.get("profileId")
        if not profile_id:
            raise FlowExecutionError("Profile node missing profileId")

        # Resolve input mapping
        input_mapping = data.get("inputMapping", "{{previous.result}}")
        query = self._resolve_template(input_mapping, context)

        if not query:
            query = context.get("query", context.get("initial_input", ""))

        client = await self._get_client()

        # 1. Create session for this profile
        try:
            session_resp = await client.post(
                f"{self.uderia_url}/api/v1/sessions",
                headers=self.headers,
                json={"profile_id": profile_id}
            )
            session_resp.raise_for_status()
            session_data = session_resp.json()
            session_id = session_data["session_id"]
            uderia_sessions.append(session_id)
        except httpx.HTTPError as e:
            raise FlowExecutionError(f"Failed to create Uderia session: {e}")

        # 2. Execute query
        try:
            task_resp = await client.post(
                f"{self.uderia_url}/api/v1/sessions/{session_id}/query",
                headers=self.headers,
                json={"prompt": query}
            )
            task_resp.raise_for_status()
            task_data = task_resp.json()
            task_id = task_data["task_id"]
        except httpx.HTTPError as e:
            raise FlowExecutionError(f"Failed to execute query: {e}")

        # 3. Poll for completion
        max_attempts = int(self.timeout)
        for attempt in range(max_attempts):
            try:
                result_resp = await client.get(
                    f"{self.uderia_url}/api/v1/tasks/{task_id}",
                    headers=self.headers
                )
                result_resp.raise_for_status()
                result_data = result_resp.json()

                status = result_data.get("status")
                if status == "completed":
                    # Extract result and token usage
                    events = result_data.get("events", [])
                    final_result = self._extract_result_from_events(events)
                    tokens = self._extract_tokens_from_events(events)

                    return {
                        "result": final_result,
                        "status": "success",
                        "session_id": session_id,
                        "task_id": task_id,
                        "tokens": tokens
                    }

                elif status == "failed":
                    error = result_data.get("error", "Unknown error")
                    raise FlowExecutionError(f"Uderia task failed: {error}")

                # Still running, wait and retry
                await asyncio.sleep(1)

            except httpx.HTTPError as e:
                raise FlowExecutionError(f"Failed to poll task status: {e}")

        raise FlowExecutionError(f"Uderia task timed out after {self.timeout}s")

    async def _execute_condition_node(self, data: dict, context: dict) -> dict:
        """Execute condition node - evaluate expression."""
        expression = data.get("expression", "true")

        # Build evaluation context
        eval_context = {
            "result": context.get("previous", {}),
            "previous": context.get("previous", {}),
            "query": context.get("query", ""),
            "true": True,
            "false": False,
            "True": True,
            "False": False,
            "None": None,
        }

        # Add node results to context
        for key, value in context.items():
            if key.startswith("node_"):
                eval_context[key] = value

        try:
            # Use simpleeval for safe expression evaluation
            result = simple_eval(expression, names=eval_context)
            branch = "true" if result else "false"
        except Exception as e:
            logger.warning(f"Error evaluating condition '{expression}': {e}")
            branch = "false"

        return {
            "expression": expression,
            "value": bool(result) if 'result' in dir() else False,
            "branch": branch,
            "status": "success"
        }

    async def _execute_merge_node(self, data: dict, context: dict, node_results: dict) -> dict:
        """Execute merge node - combine multiple inputs."""
        strategy = data.get("strategy", "concat")
        custom_merge = data.get("customMerge")

        # Collect results from all predecessors
        results = []
        for key, value in node_results.items():
            if isinstance(value, dict) and "result" in value:
                results.append(value["result"])
            else:
                results.append(value)

        if strategy == "concat":
            if all(isinstance(r, str) for r in results):
                merged = "\n\n".join(results)
            elif all(isinstance(r, list) for r in results):
                merged = [item for sublist in results for item in sublist]
            else:
                merged = results

        elif strategy == "first":
            merged = results[0] if results else None

        elif strategy == "last":
            merged = results[-1] if results else None

        elif strategy == "custom" and custom_merge:
            try:
                merged = simple_eval(custom_merge, names={"results": results})
            except Exception as e:
                logger.warning(f"Error in custom merge: {e}")
                merged = results
        else:
            merged = results

        return {
            "result": merged,
            "strategy": strategy,
            "input_count": len(results),
            "status": "success"
        }

    async def _execute_transform_node(self, data: dict, context: dict) -> dict:
        """Execute transform node - apply transformation."""
        operation = data.get("operation", "passthrough")
        expression = data.get("expression")
        output_key = data.get("outputKey", "result")

        result = context.get("previous", {})
        if isinstance(result, dict) and "result" in result:
            result = result["result"]

        if operation == "passthrough" or not expression:
            transformed = result

        else:
            try:
                eval_context = {
                    "result": result,
                    "data": result,
                    "previous": context.get("previous", {}),
                    "len": len,
                    "str": str,
                    "int": int,
                    "float": float,
                    "list": list,
                    "dict": dict,
                }
                transformed = simple_eval(expression, names=eval_context)
            except Exception as e:
                logger.warning(f"Error in transform: {e}")
                transformed = result

        return {
            "result": transformed,
            output_key: transformed,
            "operation": operation,
            "status": "success"
        }

    async def _execute_loop_node(
        self,
        data: dict,
        context: dict,
        node_results: dict,
        execution_id: str,
        event_callback
    ) -> dict:
        """Execute loop node - iterate over collection."""
        collection_expr = data.get("collection", "{{previous.result}}")
        item_variable = data.get("itemVariable", "item")
        max_iterations = data.get("maxIterations", 100)

        # Resolve collection
        collection = self._resolve_template(collection_expr, context)
        if not isinstance(collection, (list, tuple)):
            collection = [collection]

        # Limit iterations
        collection = collection[:max_iterations]

        results = []
        for i, item in enumerate(collection):
            # Create item context
            item_context = {**context, item_variable: item, "index": i}

            # TODO: Execute sub-flow for each item
            # For now, just collect items
            results.append({"item": item, "index": i})

        return {
            "result": results,
            "count": len(results),
            "status": "success"
        }

    async def _execute_human_node(
        self,
        data: dict,
        context: dict,
        execution_id: str,
        node_id: str
    ) -> dict:
        """Execute human node - pause and wait for user input."""
        prompt = data.get("prompt", "Please provide input:")
        input_type = data.get("inputType", "text")
        choices = data.get("choices")
        timeout = data.get("timeout", 3600)

        # Create human response request
        await flow_manager.create_human_response_request(
            execution_id=execution_id,
            node_id=node_id,
            prompt=prompt,
            input_type=input_type,
            choices=choices,
            timeout_seconds=timeout
        )

        # Wait for response (polling)
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = await flow_manager.get_pending_human_response(execution_id, node_id)
            if response and response.get("status") == "responded":
                return {
                    "result": response["response"],
                    "input_type": input_type,
                    "status": "success"
                }

            await asyncio.sleep(1)

        raise FlowExecutionError(f"Human response timeout after {timeout}s")

    def _get_node_input(self, node: Node, context: dict, node_results: dict) -> Any:
        """Get input data for a node."""
        if node.type == "start":
            return context.get("initial_input")
        elif node.type == "merge":
            return {k: v for k, v in node_results.items()}
        else:
            return context.get("previous")

    def _resolve_template(self, template: str, context: dict) -> Any:
        """Resolve a template string with context values."""
        if not template:
            return None

        # Simple template resolution: {{path.to.value}}
        import re
        pattern = r'\{\{([^}]+)\}\}'

        def replace_match(match):
            path = match.group(1).strip()
            parts = path.split(".")
            value = context

            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return str(value)

            return str(value) if value is not None else ""

        # If the entire template is a single placeholder, return the actual value
        if re.fullmatch(pattern, template.strip()):
            match = re.match(pattern, template.strip())
            path = match.group(1).strip()
            parts = path.split(".")
            value = context

            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return value

            return value

        # Otherwise, do string substitution
        return re.sub(pattern, replace_match, template)

    def _extract_result_from_events(self, events: list) -> Any:
        """Extract the final result from Uderia task events."""
        for event in reversed(events):
            event_data = event.get("event_data", {})
            if event_data.get("type") == "conversation_agent_complete":
                payload = event_data.get("payload", {})
                return payload.get("response", payload)

        # Fallback: look for any result
        for event in reversed(events):
            event_data = event.get("event_data", {})
            payload = event_data.get("payload", {})
            if "response" in payload:
                return payload["response"]
            if "result" in payload:
                return payload["result"]

        return None

    def _extract_tokens_from_events(self, events: list) -> dict:
        """Extract token usage from Uderia task events."""
        tokens = {"input": 0, "output": 0}

        for event in events:
            event_data = event.get("event_data", {})
            if event_data.get("type") == "conversation_agent_complete":
                payload = event_data.get("payload", {})
                tokens["input"] += payload.get("input_tokens", 0)
                tokens["output"] += payload.get("output_tokens", 0)

        return tokens

    def _summarize_result(self, result: dict) -> str:
        """Create a brief summary of a result for logging/events."""
        if not result:
            return "No result"

        if "result" in result:
            r = result["result"]
            if isinstance(r, str):
                return r[:100] + "..." if len(r) > 100 else r
            elif isinstance(r, list):
                return f"List with {len(r)} items"
            elif isinstance(r, dict):
                return f"Dict with {len(r)} keys"
            return str(r)[:100]

        return str(result)[:100]

    def _merge_final_results(self, results: list) -> Any:
        """Merge results from multiple end nodes."""
        if not results:
            return None
        if len(results) == 1:
            return results[0]

        # Extract actual results
        final = []
        for r in results:
            if isinstance(r, dict) and "result" in r:
                final.append(r["result"])
            else:
                final.append(r)

        return final


async def create_executor(uderia_base_url: str, jwt_token: str) -> FlowExecutor:
    """Create a flow executor instance."""
    return FlowExecutor(uderia_base_url, jwt_token)
