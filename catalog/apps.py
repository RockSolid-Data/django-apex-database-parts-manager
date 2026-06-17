import threading

from django.apps import AppConfig


def _sqlite_pragmas(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA cache_size=-64000;")    # 64 MB
        cursor.execute("PRAGMA mmap_size=268435456;")  # 256 MB
        cursor.execute("PRAGMA temp_store=MEMORY;")
        cursor.execute("PRAGMA busy_timeout=5000;")


def _warm_dropdown_caches():
    """Pre-populate dropdown filter caches so first page loads are fast."""
    try:
        from django.core.cache import cache
        from catalog.models import Application, Part, Unit, UnitTypeCategory

        # Application list dropdowns
        cache.get_or_set("app_make_choices",
            lambda: list(Application.objects.filter(is_active=True).exclude(make="").values_list("make", flat=True).distinct().order_by("make")),
            1800)
        cache.get_or_set("app_mfr_choices",
            lambda: list(Application.objects.filter(is_active=True).exclude(mfr="").values_list("mfr", flat=True).distinct().order_by("mfr")),
            1800)
        cache.get_or_set("app_volt_choices",
            lambda: list(Application.objects.filter(is_active=True).exclude(volt="").values_list("volt", flat=True).distinct().order_by("volt")),
            1800)
        cache.get_or_set("app_unit_type_choices",
            lambda: list(Application.objects.filter(is_active=True).exclude(unit_type_name="").values_list("unit_type_name", flat=True).distinct().order_by("unit_type_name")),
            1800)
        cache.get_or_set("app_total_count",
            lambda: Application.objects.filter(is_active=True).count(), 1800)

        # Part list dropdowns
        cache.get_or_set("part_category_choices",
            lambda: list(Part.objects.filter(is_active=True).exclude(category="").values_list("category", flat=True).distinct().order_by("category")),
            1800)
        cache.get_or_set("part_voltage_choices",
            lambda: list(Part.objects.filter(is_active=True).exclude(voltage="").values_list("voltage", flat=True).distinct().order_by("voltage")),
            1800)
        cache.get_or_set("part_total_count",
            lambda: Part.objects.filter(is_active=True).count(), 1800)

        # Unit list dropdowns
        active_units = Unit.objects.filter(is_active=True)
        cache.get_or_set("unit_family_choices",
            lambda: list(active_units.exclude(family="").values_list("family", flat=True).distinct().order_by("family")),
            1800)
        cache.get_or_set("unit_oem_choices",
            lambda: list(active_units.exclude(oem="").values_list("oem", flat=True).distinct().order_by("oem")),
            1800)
        cache.get_or_set("unit_voltage_choices",
            lambda: list(active_units.exclude(voltage="").values_list("voltage", flat=True).distinct().order_by("voltage")),
            1800)
        cache.get_or_set("unit_total_count",
            lambda: Unit.objects.filter(is_active=True).count(), 1800)

        # Unit type category tabs
        cache.get_or_set("unit_type_category_tabs",
            lambda: list(UnitTypeCategory.objects.values_list("name", "color")),
            1800)
    except Exception:
        pass


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "catalog"
    verbose_name = "Catalog"

    def ready(self):
        from django.db.backends.signals import connection_created
        connection_created.connect(_sqlite_pragmas)

        from django.db.models.signals import post_delete
        from catalog.models import PartImage, UnitImage

        post_delete.connect(_delete_image_file, sender=PartImage)
        post_delete.connect(_delete_image_file, sender=UnitImage)

        threading.Timer(2.0, _warm_dropdown_caches).start()


def _delete_image_file(sender, instance, **kwargs):
    """Remove the physical image file when a PartImage/UnitImage row is deleted."""
    img = getattr(instance, "image", None)
    if img and img.name:
        try:
            img.storage.delete(img.name)
        except Exception:
            pass
