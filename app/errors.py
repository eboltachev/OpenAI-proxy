from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import ORJSONResponse


def openai_error(status_code: int, message: str, err_type: str = "invalid_request_error", code: str | None = None):
    payload = {
        "error": {
            "message": message,
            "type": err_type,
            "param": None,
            "code": code,
        }
    }
    return ORJSONResponse(status_code=status_code, content=payload)


def raise_openai(status_code: int, message: str, err_type: str = "invalid_request_error", code: str | None = None):
    # Для случаев, где удобнее исключение
    raise HTTPException(status_code=status_code, detail={"error": {"message": message, "type": err_type, "code": code}})

