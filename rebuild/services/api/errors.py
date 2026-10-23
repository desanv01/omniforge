from fastapi.responses import JSONResponse
from services.api.contracts import ErrorEnvelope


class Problem(Exception):
    def __init__(self, status, code, category, message, retryable=False):
        self.status, self.code, self.category = status, code, category
        self.message, self.retryable = message, retryable


def response(request_id, status, code, category, message, retryable=False, headers=None):
    body = ErrorEnvelope(code=code, category=category, message=message,
                         retryable=retryable, request_id=request_id)
    return JSONResponse(body.model_dump(mode="json"), status_code=status,
                        headers=headers or {})
