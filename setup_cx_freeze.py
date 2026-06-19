"""
cx_Freeze setup -- builds standalone .exe (freeze only).
Inno Setup handles the installer (installer.iss).
"""
import shutil
import sys
import uuid
from pathlib import Path

from cx_Freeze import Executable, setup
from cx_Freeze.command.build_exe import build_exe as _build_exe

# =========================================================================
# PROJECT CONFIG
# =========================================================================
APP_NAME = "ApexDatabase"
APP_DISPLAY_NAME = "Apex Database"
APP_DESCRIPTION = "Catalog, Inventory & Invoicing"
APP_AUTHOR = "Rock Solid Data"
DJANGO_PROJECT = "config"

BASE_DIR = Path(__file__).parent
APP_VERSION = (BASE_DIR / "VERSION").read_text().strip()


def get_or_create_upgrade_code():
    code_file = BASE_DIR / ".upgrade_code"
    if code_file.exists():
        return code_file.read_text().strip()
    code = "{" + str(uuid.uuid4()).upper() + "}"
    code_file.write_text(code + "\n")
    print(f"Generated new UPGRADE_CODE: {code}")
    print(f"Saved to {code_file} -- commit this file to version control!")
    return code


UPGRADE_CODE = get_or_create_upgrade_code()

PACKAGES = [
    "django", "django.contrib", "django.contrib.admin",
    "django.contrib.admin.migrations", "django.contrib.admin.templatetags",
    "django.contrib.admin.views", "django.contrib.auth",
    "django.contrib.auth.migrations", "django.contrib.auth.handlers",
    "django.contrib.contenttypes", "django.contrib.contenttypes.migrations",
    "django.contrib.sessions", "django.contrib.sessions.migrations",
    "django.contrib.messages", "django.contrib.staticfiles",
    "django.contrib.humanize", "django.contrib.humanize.templatetags",
    "django.template", "django.template.backends",
    "django.template.backends.django", "django.template.loaders",
    "django.templatetags", "django.db", "django.db.backends",
    "django.db.backends.sqlite3", "django.db.migrations",
    "django.core", "django.core.management",
    "django.core.management.commands", "django.forms",
    "django.views", "django.utils",

    DJANGO_PROJECT,
    "config.settings",
    "catalog", "catalog.migrations", "catalog.management",
    "catalog.management.commands", "catalog.templatetags",
    "inventory", "inventory.migrations", "inventory.templatetags",
    "invoicing", "invoicing.migrations", "invoicing.management",
    "invoicing.management.commands",
    "data_import", "data_import.management", "data_import.management.commands",
    "data_import.pdf_parsers",
    "backup", "backup.migrations",

    "waitress", "waitress.adjustments", "waitress.channel",
    "waitress.parser", "waitress.receiver", "waitress.task",
    "waitress.trigger", "waitress.utilities",
    "whitenoise", "whitenoise.middleware", "whitenoise.storage",
    "asgiref", "sqlparse",

    "config.middleware", "config.context_processors",

    "PIL",
    "pdfplumber", "pdfminer", "pdfminer.high_level",
    "charset_normalizer", "charset_normalizer.md",
    "fitz", "pymupdf",
    "html.parser", "http.cookies", "http.server",
    "email", "email.policy", "email.headerregistry",
    "email._header_value_parser", "email.mime", "email.mime.text",
    "email.mime.multipart", "email.mime.base",
    "xml.etree", "xml.etree.ElementTree",
    "sqlite3", "decimal", "datetime", "json", "re", "hashlib",
    "secrets", "uuid", "logging", "logging.handlers", "pathlib",
    "urllib", "urllib.parse", "threading", "webbrowser",
    "copy", "functools", "itertools", "operator",
    "collections", "collections.abc", "io", "zoneinfo",
    "encodings", "multiprocessing", "csv",
]

EXCLUDES = [
    "tkinter", "test", "unittest", "pytest", "pydoc", "doctest",
    "xmlrpc", "curses", "distutils", "setuptools", "pip",
    "ensurepip", "venv", "lib2to3", "idlelib", "turtledemo",
    "numpy", "scipy", "matplotlib", "pandas",
    "IPython", "jupyter", "notebook", "cx_Freeze",
]

INT = "_internal"

INCLUDE_FILES = [
    (str(BASE_DIR / "VERSION"), f"{INT}/VERSION"),
    (str(BASE_DIR / "version.py"), f"{INT}/version.py"),
    (str(BASE_DIR / "loading.html"), f"{INT}/loading.html"),
    (str(BASE_DIR / "python312._pth"), "python312._pth"),
]

if (BASE_DIR / "changelog.json").exists():
    INCLUDE_FILES.append((str(BASE_DIR / "changelog.json"), f"{INT}/changelog.json"))

if (BASE_DIR / "seed.sqlite3").exists():
    INCLUDE_FILES.append((str(BASE_DIR / "seed.sqlite3"), f"{INT}/seed.sqlite3"))

if (BASE_DIR / ".media_version").exists():
    INCLUDE_FILES.append((str(BASE_DIR / ".media_version"), f"{INT}/.media_version"))

if (BASE_DIR / "staticfiles").is_dir():
    INCLUDE_FILES.append((str(BASE_DIR / "staticfiles"), f"{INT}/staticfiles"))

if (BASE_DIR / "templates").is_dir():
    INCLUDE_FILES.append((str(BASE_DIR / "templates"), "lib/templates"))

ICON_PATH = BASE_DIR / "app.ico"
if not ICON_PATH.exists():
    ICON_PATH = None
    print("WARNING: app.ico not found -- using default icon.")

INCLUDES = ["email._header_value_parser"]

# charset_normalizer uses mypyc-compiled extensions that reference a top-level
# runtime module with a hash-based name. cx_Freeze can't auto-detect it.
import glob as _glob

for _site_packages in (BASE_DIR / "venv", BASE_DIR / ".venv"):
    for _pyd in _glob.glob(str(_site_packages / "Lib/site-packages/*__mypyc*.pyd")):
        INCLUDE_FILES.append((_pyd, f"lib/{Path(_pyd).name}"))

# zip_exclude_packages copies entire Django app trees into lib/, including dev-only
# import staging databases. These must never ship to end users.
FREEZE_EXCLUDE_BUILD_PATHS = [
    Path("lib") / "data_import" / "staging_dbs",
]


def prune_dev_assets(build_exe_dir: Path) -> None:
    for rel_path in FREEZE_EXCLUDE_BUILD_PATHS:
        target = build_exe_dir / rel_path
        if target.exists():
            shutil.rmtree(target)
            print(f"Removed dev-only assets: {rel_path}")


class build_exe(_build_exe):
    """Prune dev-only package data after cx_Freeze copies zip_exclude_packages."""

    def run(self):
        super().run()
        prune_dev_assets(Path(self.build_exe))


BUILD_OPTIONS = {
    "packages": PACKAGES,
    "includes": INCLUDES,
    "excludes": EXCLUDES,
    "include_files": INCLUDE_FILES,
    "include_msvcr": False,
    "optimize": 0,
    "build_exe": f"build/{APP_NAME}",
    "zip_exclude_packages": [
        "django", DJANGO_PROJECT,
        "catalog", "inventory", "invoicing", "data_import", "backup",
    ],
}

executables = [
    Executable(script="launcher.py", base="gui",
               target_name=f"{APP_NAME}.exe",
               icon=str(ICON_PATH) if ICON_PATH else None),
    Executable(script="launcher.py", base="console",
               target_name=f"{APP_NAME}_Debug.exe",
               icon=str(ICON_PATH) if ICON_PATH else None),
]

setup(
    name=APP_NAME, version=APP_VERSION,
    description=APP_DESCRIPTION, author=APP_AUTHOR,
    options={"build_exe": BUILD_OPTIONS},
    executables=executables,
    cmdclass={"build_exe": build_exe},
)
