import logging
import time

logger = logging.getLogger("activity")

_SKIP_PREFIXES = ("/static/", "/favicon.ico", "/__debug__/")


class ActivityLogMiddleware:
    """Log every request to the console so the operator can follow along
    in the runserver terminal.  POST requests (saves / deletes) are
    logged at INFO; regular GETs at DEBUG so they can be silenced if
    desired without losing mutation visibility.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return self.get_response(request)

        t0 = time.monotonic()
        response = self.get_response(request)
        ms = (time.monotonic() - t0) * 1000

        status = response.status_code
        method = request.method
        level = logging.INFO if method == "POST" or status >= 400 else logging.DEBUG

        logger.log(
            level,
            "%s %s → %s (%.0f ms)",
            method,
            path,
            status,
            ms,
        )
        return response
