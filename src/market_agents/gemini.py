"""Narrow Gemini JSON gateway. Errors degrade to deterministic results, never fake data."""
from __future__ import annotations
import json
import time
from jsonschema import validate
from .guardrails import sanitize_agent_result


def ask_json(client, model: str, system: str, payload: dict, schema: dict, on_event, name: str) -> dict:
    from google.genai import types
    last = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=json.dumps(payload, default=str, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=system, response_mime_type="application/json",
                    response_json_schema=schema, temperature=0),
            )
            result = json.loads(response.text)
            validate(result, schema)
            result, filtered_fields = sanitize_agent_result(result)
            if filtered_fields:
                on_event("agent_output_guardrail", agent=name, filtered_fields=filtered_fields)
            on_event("agent_response", agent=name, response=result)
            return result
        except Exception as err:
            last = err
            message = str(err)
            recoverable = any(token in message for token in ("502", "503", "UNAVAILABLE", "Bad Gateway"))
            on_event("agent_error", agent=name, retry=bool(recoverable and attempt < 2),
                     attempt=attempt + 1, error=message[:250])
            if recoverable and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            break
    raise RuntimeError(f"{name} failed: {str(last)[:280]}")
