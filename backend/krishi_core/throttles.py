"""Rate limits for endpoints that spend Google Gemini quota.

Logged-in users are limited per account, anonymous callers per IP address.
The rate is configurable with AI_THROTTLE_RATE (default "40/hour").
"""
from rest_framework.throttling import UserRateThrottle


class AIRateThrottle(UserRateThrottle):
    scope = "ai"
