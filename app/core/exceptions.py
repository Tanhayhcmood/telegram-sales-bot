from fastapi import HTTPException, status


class AppException(Exception):
    def __init__(self, message: str, code: str = "APP_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundError(AppException):
    def __init__(self, resource: str, resource_id: str = ""):
        super().__init__(f"{resource} not found: {resource_id}", "NOT_FOUND")


class ConflictError(AppException):
    def __init__(self, message: str):
        super().__init__(message, "CONFLICT")


class ValidationError(AppException):
    def __init__(self, message: str):
        super().__init__(message, "VALIDATION_ERROR")


class AuthenticationError(AppException):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "AUTH_ERROR")


class TelegramError(AppException):
    def __init__(self, message: str):
        super().__init__(message, "TELEGRAM_ERROR")


class AIServiceError(AppException):
    def __init__(self, message: str):
        super().__init__(message, "AI_ERROR")


class DatabaseError(AppException):
    def __init__(self, message: str):
        super().__init__(message, "DB_ERROR")


class SpamDetectedError(AppException):
    def __init__(self, user_id: int):
        super().__init__(f"Spam detected from user {user_id}", "SPAM_DETECTED")


def http_404(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def http_403(detail: str = "Forbidden") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def http_401(detail: str = "Unauthorized") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def http_409(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
