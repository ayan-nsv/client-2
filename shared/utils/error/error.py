from fastapi import HTTPException


class Error(HTTPException):
    def __init__(self, message: str, status_code: int, headers: dict = None):
        super().__init__(status_code=status_code, detail=message, headers=headers)

class TooManyRequests(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=429, headers=headers)
    def __str__(self):
        return f"Too many requests: {self.detail}"

class PermissionDenied(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=403, headers=headers)
    def __str__(self):
        return f"Permission denied: {self.detail}"

class NotFound(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=404, headers=headers)
    def __str__(self):
        return f"Not found: {self.detail}"

class BadRequest(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=400, headers=headers)
    def __str__(self):
        return f"Bad request: {self.detail}"

class InternalServerError(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=500, headers=headers)
    def __str__(self):
        return f"Internal server error: {self.detail}"
class AlreadyExists(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=409, headers=headers)
    def __str__(self):
        return f"Bad request: {self.detail}"
class EmailAlreadyInUseError(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=409, headers=headers)
    def __str__(self):
        return f"Email already exists, please login: {self.detail}"
class EmailPendingApprovalError(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=409, headers=headers)
    def __str__(self):
        return f"Email under review, try again later: {self.detail}"
class EmailServiceError(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=409, headers=headers)
    def __str__(self):
        return f"Something wrong with the email service: {self.detail}"

class Forbidden(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=403, headers=headers)
    def __str__(self):
        return f"Forbidden: {self.detail}"
  
class Unauthorized(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=401, headers=headers)
    def __str__(self):
        return f"Unauthorized: {self.detail}"
  
class ServiceUnavailable(Error):
    def __init__(self, message: str, headers: dict = None):
        super().__init__(message=message, status_code=503, headers=headers)
    def __str__(self):
        return f"Service unavailable: {self.detail}"


