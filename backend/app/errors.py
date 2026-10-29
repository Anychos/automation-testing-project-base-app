from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message

def install_errors(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(part) for part in err["loc"] if part != "body"), "message": err["msg"]} for err in exc.errors()]
        return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": "Неверные данные", "fields": errors}}, status_code=422)
