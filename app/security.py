import time
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects essential security headers into every HTTP response."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
        )
        return response


class SimpleRateLimiter:
    """In-memory rate limiter to prevent API endpoint spam and denial-of-service."""
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.client_history: dict[str, list[float]] = {}

    def check_rate_limit(self, client_ip: str):
        now = time.time()
        window_start = now - 60.0
        
        # Clean up timestamps older than 60 seconds
        history = [t for t in self.client_history.get(client_ip, []) if t > window_start]
        
        if len(history) >= self.requests_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later."
            )
        
        history.append(now)
        self.client_history[client_ip] = history