"""
URL configuration for the Apex Database project.
"""

import re as _re

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("catalog.urls")),
    path("inventory/", include("inventory.urls")),
    path("invoicing/", include("invoicing.urls")),
    path("backup/", include("backup.urls")),
]

# Serve media unconditionally (desktop app on localhost — no security concern).
urlpatterns += [
    re_path(
        r"^%s(?P<path>.*)$" % _re.escape(settings.MEDIA_URL.lstrip("/")),
        serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
