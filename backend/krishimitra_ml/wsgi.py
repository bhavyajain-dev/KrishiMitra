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
