from django.urls import path

from . import views

app_name = "backup"

urlpatterns = [
    path("", views.backup_settings_view, name="settings"),
    path("now/", views.backup_now_view, name="now"),
    path("restore/", views.backup_restore_view, name="restore"),
    path("api/pick-folder/", views.api_pick_folder, name="api_pick_folder"),
    path("api/pick-file/", views.api_pick_file, name="api_pick_file"),
]
