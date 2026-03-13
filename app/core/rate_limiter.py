"""
Centralised SlowAPI rate limiter configuration.

Key design goals:
- Correct client IP extraction when running behind reverse proxies / load balancers
  (AWS ALB, Nginx, Cloudflare) using X-Forwarded-For / X-Real-IP.
- Single Limiter instance shared by all endpoints (/analyze, /detect, etc.).
"""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def forwarded_for_key(request: Request) -> str:
    """
    Resolve the best-effort client IP address for rate limiting.

    Priority:
    1. X-Forwarded-For: first IP in the list (left-most, original client).
    2. X-Real-IP: commonly set by reverse proxies.
    3. Fallback to slowapi.util.get_remote_address (request.client.host).

    This prevents the classic "all users share the load balancer IP" problem
    where a single IP-based rate limit would throttle thousands of users.
    """
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        # X-Forwarded-For: client, proxy1, proxy2, ...
        client_ip = xff.split(",")[0].strip()
        if client_ip:
            return client_ip

    real_ip = request.headers.get("x-real-ip") or request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    return get_remote_address(request)


# Shared limiter instance; default limit is intentionally generous and safe for
# production. Endpoint-specific decorators (e.g. 10/min on /analyze) still
# apply on top of this global budget.
limiter = Limiter(key_func=forwarded_for_key, default_limits=["200/minute"])

