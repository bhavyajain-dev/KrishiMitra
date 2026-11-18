from django.apps import AppConfig


def _is_server_process():
    """True only in a process that actually serves requests.

    - gunicorn (production on Render): always a server.
    - ``manage.py runserver``: only the reloader's child (RUN_MAIN=true), so the
      jobs don't start twice.
    - Any other management command (migrate, test, collectstatic, shell...):
      never start background jobs.
    """
    import os
    import sys

    argv0 = os.path.basename(sys.argv[0]) if sys.argv else ""
    if "gunicorn" in argv0:
        return True
    if len(sys.argv) > 1 and sys.argv[1] == "runserver":
        return os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv
    return False


class KrishiCoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'krishi_core'

    def ready(self):
        from django.conf import settings
        if _is_server_process():
            # Build AI Mitra's knowledge-base index in the background so the
            # first chat after a restart doesn't pay for it.
            from .services.kb_search import warm_up
            warm_up()
        # Only run jobs if the scheduler is explicitly enabled AND this process
        # is a real server (previously this checked RUN_MAIN only, which is set
        # by runserver's reloader and never by gunicorn, so jobs never ran in
        # production).
        if not getattr(settings, 'ENABLE_SCHEDULER', False):
            return
        if not _is_server_process():
            return
        from .jobs import start_jobs
        start_jobs()
