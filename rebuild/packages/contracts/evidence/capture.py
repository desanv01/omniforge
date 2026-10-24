"""Capture instant plus original RFC3339 representation; never infer provenance."""
from datetime import datetime, timezone
import re
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$")


def parse_capture(value):
    if value is None:
        return {"captured_at": None, "captured_at_original": None,
                "captured_at_offset": None, "captured_at_provenance": "unknown"}
    match = RFC3339.fullmatch(value)
    if match is None:
        raise ValueError("Capture timestamp must be RFC3339 with explicit offset")
    offset = match.group(1)
    if offset != "Z" and (int(offset[1:3]) > 23 or int(offset[4:6]) > 59):
        raise ValueError("Invalid RFC3339 offset")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return {"captured_at": parsed.astimezone(timezone.utc), "captured_at_original": value,
            "captured_at_offset": match.group(1), "captured_at_provenance": "supplied"}


class CaptureTime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    captured_at: AwareDatetime | None = None
    captured_at_original: str | None = None
    captured_at_offset: str | None = None
    captured_at_provenance: Literal["supplied", "unknown"] = "unknown"

    @model_validator(mode="after")
    def consistent(self):
        if self.captured_at_provenance == "unknown":
            if self.captured_at_original is not None or self.captured_at_offset is not None:
                raise ValueError("Unknown provenance cannot supply an invented original")
        else:
            expected = parse_capture(self.captured_at_original)
            if (self.captured_at is None or expected["captured_at"] != self.captured_at
                    or expected["captured_at_offset"] != self.captured_at_offset):
                raise ValueError("Capture instant and original representation disagree")
        if self.captured_at is not None:
            self.captured_at = self.captured_at.astimezone(timezone.utc)
        return self
