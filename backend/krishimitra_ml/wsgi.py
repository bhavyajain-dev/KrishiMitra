import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "krishimitra_ml.settings")
application = get_wsgi_application()

# Import every view module (and with it numpy, pandas, scikit-learn) now, in
# the main thread, before gunicorn starts its request threads. Django would
# otherwise import the URLconf lazily inside the first request thread, and
# heavy C-extension imports racing across threads can leave a module half
# initialised for every later request. This also makes the first request fast.
from django.urls import get_resolver  # noqa: E402

get_resolver().url_patterns

# Build AI Mitra's knowledge-base index now (main thread, before serving), so
# the first chat after a restart or wake-up doesn't wait ~15 s for it.
try:
    from krishi_core.services.kb_search import _get_index

    _get_index()
except Exception:  # never block startup; chat builds it on first use instead
    import logging

    logging.getLogger(__name__).warning("Knowledge index warm-up failed", exc_info=True)
