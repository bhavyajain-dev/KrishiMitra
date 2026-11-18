"""JWT authentication that does not lock visitors out of public endpoints."""
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


class PublicFriendlyJWTAuthentication(JWTAuthentication):
    """Standard JWT auth, except on endpoints anyone may use.

    A browser can hold an expired token (or send "Bearer null" before login).
    Plain JWTAuthentication rejects such requests with 401 even on public
    endpoints like market prices or geocoding, so the page breaks until the
    user logs in again. Here a bad token on a public endpoint just means
    "anonymous visitor". Protected endpoints still answer 401 as before, so
    the frontend's log-out-on-401 behaviour is unchanged.
    """

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except (InvalidToken, AuthenticationFailed):
            if self._is_public(request):
                return None
            raise

    @staticmethod
    def _is_public(request):
        view = (getattr(request, "parser_context", None) or {}).get("view")
        if view is None:
            return False
        try:
            perms = view.get_permissions()
        except Exception:
            return False
        return bool(perms) and all(isinstance(p, AllowAny) for p in perms)
