"""Deterministic synthetic transport, never a live capability proof."""
import json


def tool_round(location):
    return {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant",
        "content": None, "tool_calls": [{"id": "read-1", "type": "function", "function": {
            "name": "read_evidence_range", "arguments": json.dumps({"location_id": str(location.id),
                "expected_sha256": location.sha256, "start_byte": location.start_byte,
                "end_byte": location.end_byte})}}]}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 20}}


def final_round(location):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({
        "observations": [{"text": "Synthetic range was read; no real-world conclusion is asserted.",
            "citations": [{"location_id": str(location.id), "expected_sha256": location.sha256}],
            "coverage": "partial"}], "claims": [], "outcome": "answered", "reason": "Synthetic fixture only."})}}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 25}}


class ScriptedMock:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def complete(self, profile, secret, payload, timeout):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response
