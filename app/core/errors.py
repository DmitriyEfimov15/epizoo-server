from fastapi import HTTPException


def not_found(message: str):
    return HTTPException(status_code=404, detail={"code": "not_found", "message": message})


def invalid(message: str):
    return HTTPException(status_code=422, detail={"code": "validation_error", "message": message})
