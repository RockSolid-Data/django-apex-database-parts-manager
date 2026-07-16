"""
Apex Database - Desktop App Launcher
Entry point for the frozen application.
"""

import json
import os
import signal
import sys
import time
import shutil
import socket
import string
import msvcrt
import zipfile
import threading
import webbrowser
import subprocess
from datetime import datetime
from pathlib import Path

DEFAULT_PORT = 8000
MAX_PORT = 8010


def is_frozen():
    return getattr(sys, 'frozen', False)


def is_debug_exe():
    """True when running as the *_Debug.exe console build."""
    if is_frozen():
        return Path(sys.executable).stem.endswith('_Debug')
    return True


def get_app_exe_name():
    """Derive the app name from the running executable (strips _Debug suffix)."""
    if is_frozen():
        name = Path(sys.executable).stem
        if name.endswith('_Debug'):
            name = name[:-6]
        return name
    identity_file = Path(__file__).parent / ".app_identity"
    if identity_file.exists():
        try:
            return json.loads(identity_file.read_text(encoding="utf-8"))["app_name"]
        except Exception:
            pass
    return Path(__file__).parent.name


def get_app_dir():
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_data_dir():
    app_name = get_app_exe_name()
    if is_frozen():
        local_app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        data_dir = Path(local_app_data) / app_name
    else:
        data_dir = get_app_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def setup_logging():
    """Redirect stdout/stderr to a log file so errors are always captured.

    Debug.exe keeps output on the console AND tees to the log file so the
    user can see errors directly in the terminal window.
    """
    if not is_frozen():
        return

    log_dir = get_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "launcher.log"

    try:
        log_fh = open(log_path, "a", encoding="utf-8", buffering=1)

        if is_debug_exe():
            sys.stdout = _TeeWriter(sys.__stdout__, log_fh)
            sys.stderr = _TeeWriter(sys.__stderr__, log_fh)
        else:
            sys.stdout = log_fh
            sys.stderr = log_fh

        print(f"\n{'=' * 60}")
        print(f"  Launcher started at {datetime.now():%Y-%m-%d %H:%M:%S}")
        print(f"  Executable: {sys.executable}")
        print(f"{'=' * 60}")
    except Exception:
        pass


class _TeeWriter:
    """Write to two streams simultaneously (console + log file)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


_lock_fh = None


def acquire_lock(data_dir):
    global _lock_fh
    lock_path = data_dir / '.lock'
    try:
        _lock_fh = open(lock_path, 'w')
        msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def find_running_instance_port():
    """Check if our app is already listening on any port in the range."""
    for port in range(DEFAULT_PORT, MAX_PORT + 1):
        if is_port_in_use(port):
            pid = find_pid_on_port(port)
            if pid and is_our_app_process(pid):
                return port
    return None


def setup_django():
    app_dir = get_app_dir()
    internal_dir = app_dir / '_internal' if is_frozen() else app_dir

    if str(internal_dir) not in sys.path:
        sys.path.insert(0, str(internal_dir))
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.frozen')

    os.environ['APP_FROZEN'] = '1' if is_frozen() else '0'
    os.environ['APP_DIR'] = str(internal_dir)
    os.environ['APP_DATA_DIR'] = str(get_data_dir())
    os.environ['APP_NAME'] = get_app_exe_name()

    import django
    django.setup()


def ensure_database():
    """Set up the database for the frozen app.

    First install:  copy seed.sqlite3 as db.sqlite3
    Upgrade:        keep existing db.sqlite3, sync new catalog records from seed
    """
    data_dir = get_data_dir()
    db_path = data_dir / "db.sqlite3"
    app_dir = get_app_dir()
    internal_dir = app_dir / '_internal' if is_frozen() else app_dir
    seed_path = internal_dir / "seed.sqlite3"

    os.environ['DATABASE_PATH'] = str(db_path)

    if not db_path.exists():
        if seed_path.exists():
            print(f"First install: copying seed database to {db_path}")
            shutil.copy2(seed_path, db_path)
        else:
            print("No seed database found; a new empty database will be created.")
        return "first_install"
    else:
        print(f"Existing database found at {db_path}")
        return "upgrade"


MEDIA_ZIP_NAME = "ApexDatabase_Media.zip"
MEDIA_VERSION_FILE = ".media_version"
MEDIA_STATUS_FILE = ".media_status.json"
MEDIA_MIN_FILES = 10


def _write_media_status(extracting=True, current=0, total=0, message=""):
    """Write media extraction progress to a JSON file for the Django status endpoint."""
    try:
        status_path = get_data_dir() / MEDIA_STATUS_FILE
        payload = json.dumps({
            "extracting": extracting,
            "current": current,
            "total": total,
            "message": message,
        })
        tmp = status_path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(status_path)
    except Exception:
        pass


def _clear_media_status():
    _write_media_status(extracting=False)


def _count_files(directory):
    """Count files in a directory tree (non-recursive stat for speed)."""
    count = 0
    try:
        for _, _, files in os.walk(directory):
            count += len(files)
            if count >= MEDIA_MIN_FILES:
                return count
    except OSError:
        pass
    return count


def _get_bundled_media_version():
    """Read the expected media version from the build."""
    app_dir = get_app_dir()
    internal_dir = app_dir / '_internal' if is_frozen() else app_dir
    version_path = internal_dir / MEDIA_VERSION_FILE
    if version_path.exists():
        return version_path.read_text(encoding="utf-8").strip()
    return None


def _get_installed_media_version(data_dir):
    """Read the media version currently on disk."""
    version_path = data_dir / "media" / MEDIA_VERSION_FILE
    if version_path.exists():
        return version_path.read_text(encoding="utf-8").strip()
    return None


def _find_media_zip():
    """Search for the media zip in likely locations."""
    candidates = []

    app_dir = get_app_dir()

    # 1. Install directory and _internal
    candidates.append(app_dir)
    internal = app_dir / '_internal' if is_frozen() else app_dir
    candidates.append(internal)

    # 2. One folder up from install dir (USB root if installed to subfolder)
    candidates.append(app_dir.parent)

    # 3. Data directory (where db.sqlite3 lives)
    candidates.append(get_data_dir())

    # 4. Common user folders (Downloads, Desktop)
    user_home = Path.home()
    candidates.append(user_home / "Downloads")
    candidates.append(user_home / "Desktop")

    # 5. All drive roots including C:\ (covers USB drives and local copies)
    for letter in string.ascii_uppercase[2:]:  # C through Z
        drive = Path(f"{letter}:\\")
        if drive.exists():
            candidates.append(drive)

    seen = set()
    for folder in candidates:
        folder = folder.resolve()
        if folder in seen:
            continue
        seen.add(folder)
        candidate = folder / MEDIA_ZIP_NAME
        if candidate.is_file():
            print(f"  Found media pack: {candidate}")
            return candidate

    return None


def _zip_is_valid(path):
    """True if ``path`` is a readable zip (parses its central directory)."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            zf.namelist()
        return True
    except (zipfile.BadZipFile, OSError):
        return False


def ensure_media_pack():
    """Ensure the media pack zip is present in the data dir.

    Part images are served on demand straight from this zip (see
    ``config.media_utils.serve_media``) -- there is no extraction step, so there
    is no first-launch wait and no partial-extraction corruption to heal.

    The installer copies the pack into the data dir during install, so on a
    normal install this is a fast no-op. It also acts as a safety net: for
    manual installs / dev where the pack is only on a USB drive or in the
    install folder, it copies that single file into the data dir (with a size
    check) so images keep working after the USB is removed.
    """
    data_dir = get_data_dir()
    dest = data_dir / MEDIA_ZIP_NAME

    if dest.is_file():
        if _zip_is_valid(dest):
            return
        # Corrupt / partially-copied pack -- drop it so we re-copy a good one.
        print("  Existing media pack is invalid -- replacing it.")
        try:
            dest.unlink()
        except OSError:
            pass

    src = _find_media_zip()
    if not src:
        print("  No media pack found. Part images will not be available.")
        print(f"  Place {MEDIA_ZIP_NAME} next to the installer or on a USB drive.")
        return

    if src.resolve() == dest.resolve():
        return  # already the canonical copy in the data dir

    print(f"  Copying media pack to {dest}...")
    _write_media_status(True, 0, 0, "Preparing part images\u2026")
    tmp = dest.with_suffix(".part")
    try:
        shutil.copyfile(src, tmp)
        if src.stat().st_size != tmp.stat().st_size:
            raise IOError("size mismatch after copy")
        os.replace(tmp, dest)
        print("  Media pack ready.")
    except Exception as e:
        print(f"  Media pack copy error: {e}")
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def ensure_media():
    """Ensure media files are up to date.

    - Empty/missing media folder: full extraction
    - Media exists but version differs: incremental (only add new files)
    - Media exists and version matches: skip (fast path)
    """
    data_dir = get_data_dir()
    media_dir = data_dir / "media"

    has_media = media_dir.is_dir() and _count_files(media_dir) >= MEDIA_MIN_FILES

    if has_media:
        bundled_version = _get_bundled_media_version()
        installed_version = _get_installed_media_version(data_dir)

        if bundled_version and bundled_version == installed_version:
            return

        # Versions differ (or no version file yet) — do incremental sync
        zip_path = _find_media_zip()
        if not zip_path:
            return

        print("Checking for new media files...")
        _incremental_media_sync(zip_path, data_dir, media_dir)
        return

    # No media at all — full extraction
    print("Media folder is empty -- searching for media pack...")
    zip_path = _find_media_zip()
    if not zip_path:
        print("  No media pack found. Images will not be available.")
        print(f"  Place {MEDIA_ZIP_NAME} next to the installer or on a USB drive.")
        return

    media_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Extracting media files to {media_dir}...")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()
            total = len(members)
            _write_media_status(True, 0, total, "Extracting media files\u2026")
            for i, member in enumerate(members, 1):
                zf.extract(member, data_dir)
                if i % 500 == 0 or i == total:
                    pct = i * 100 // total
                    print(f"  Extracting... {i:,}/{total:,} ({pct}%)")
                    _write_media_status(True, i, total, "Extracting media files\u2026")

        print(f"  Media extraction complete ({total:,} files).")
    except Exception as e:
        print(f"  Media extraction error: {e}")
        import traceback
        traceback.print_exc()


def _incremental_media_sync(zip_path, data_dir, media_dir):
    """Extract only files from the zip that don't exist on disk."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            all_members = zf.namelist()
            missing = []
            for member in all_members:
                if member.endswith("/"):
                    continue
                target = data_dir / member
                if not target.exists():
                    missing.append(member)

            if not missing:
                print("  Media is up to date (no new files).")
            else:
                total_missing = len(missing)
                print(f"  Adding {total_missing:,} new media files...")
                _write_media_status(True, 0, total_missing, "Syncing new media files\u2026")
                for i, member in enumerate(missing, 1):
                    zf.extract(member, data_dir)
                    if i % 200 == 0 or i == total_missing:
                        pct = i * 100 // total_missing
                        print(f"  Syncing... {i:,}/{total_missing:,} ({pct}%)")
                        _write_media_status(True, i, total_missing, "Syncing new media files\u2026")
                print(f"  Media sync complete ({total_missing:,} new files added).")

        # Update the installed version marker
        bundled_version = _get_bundled_media_version()
        if bundled_version:
            version_path = media_dir / MEDIA_VERSION_FILE
            version_path.write_text(bundled_version + "\n", encoding="utf-8")

    except Exception as e:
        print(f"  Media sync error: {e}")
        import traceback
        traceback.print_exc()


def run_migrations():
    from django.core.management import call_command
    print("Running database migrations...")
    try:
        call_command('migrate', verbosity=1)
        print("Migrations complete.")
        return True
    except Exception as e:
        if "already exists" not in str(e):
            print(f"Migration error: {e}")
            import traceback
            traceback.print_exc()
            return False

        print(f"Tables already exist (seeded DB). Syncing migration state...")
        try:
            call_command('migrate', '--fake', verbosity=1)
            print("Migration state synced. Running any pending migrations...")
            call_command('migrate', verbosity=1)
            print("Migrations complete.")
            return True
        except Exception as e2:
            print(f"Migration sync failed: {e2}")
            import traceback
            traceback.print_exc()
            return False


CATALOG_SYNC_TIMEOUT_SECONDS = 90


def sync_catalog_data():
    """Sync new catalog records from the bundled seed database.

    Runs on every upgrade. The sync_catalog command handles:
    - INSERT OR IGNORE for new records (safe against UNIQUE conflicts)
    - Per-table commits so partial progress is saved on failure

    Hardened against the v1.2.2 hang: runs in a worker thread with a hard
    timeout so a slow/broken sync can NEVER prevent the server from starting.
    If the timeout fires we just log a warning and move on -- the customer's
    DB is untouched (per-table commits + INSERT-only default).
    """
    app_dir = get_app_dir()
    internal_dir = app_dir / '_internal' if is_frozen() else app_dir
    seed_path = internal_dir / "seed.sqlite3"

    if not seed_path.exists():
        print("No seed database found -- skipping catalog sync.")
        return

    from io import StringIO

    stdout_capture = StringIO()
    stderr_capture = StringIO()
    error_holder = {"exc": None}

    def _runner():
        try:
            from django.core.management import call_command
            call_command(
                'sync_catalog',
                seed_db=str(seed_path),
                # Inner time budget: a few seconds below the thread timeout so
                # the SQL itself aborts cleanly instead of being abandoned.
                max_seconds=max(10, CATALOG_SYNC_TIMEOUT_SECONDS - 10),
                verbosity=1,
                stdout=stdout_capture,
                stderr=stderr_capture,
            )
        except Exception as exc:
            error_holder["exc"] = exc

    print("Syncing catalog data from seed (max "
          f"{CATALOG_SYNC_TIMEOUT_SECONDS}s)...")
    worker = threading.Thread(target=_runner, name="catalog-sync", daemon=True)
    worker.start()
    worker.join(timeout=CATALOG_SYNC_TIMEOUT_SECONDS)

    if worker.is_alive():
        print(
            f"[SYNC TIMEOUT] Catalog sync did not finish within "
            f"{CATALOG_SYNC_TIMEOUT_SECONDS}s -- continuing startup anyway. "
            "Your existing data is unchanged. Re-run later with "
            "'manage.py sync_catalog --seed-db ... --fill-blanks' if you "
            "want to fill in missing fields."
        )
        return

    stdout_text = stdout_capture.getvalue()
    stderr_text = stderr_capture.getvalue()

    if stdout_text.strip():
        print(stdout_text.rstrip())
    if stderr_text.strip():
        print(f"[SYNC WARNINGS]\n{stderr_text.rstrip()}")

    if error_holder["exc"] is not None:
        exc = error_holder["exc"]
        print(f"[SYNC ERROR] Catalog sync failed: {exc}")
        import traceback
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        print(
            "  The application will continue, but some catalog data may be "
            "missing. Check the log file for details."
        )
        return

    print("Catalog sync complete.")


def create_superuser_if_needed():
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if User.objects.count() == 0:
            User.objects.create_superuser(
                username='admin', email='admin@localhost', password='admin',
            )
            print("Default admin created (admin / admin) -- change after first login!")
    except Exception as e:
        print(f"Could not create admin user: {e}")


def is_port_in_use(port, host='127.0.0.1'):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def find_pid_on_port(port):
    try:
        result = subprocess.run(
            ['netstat', '-ano', '-p', 'TCP'],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f':{port}' in parts[1] and parts[3] == 'LISTENING':
                return int(parts[4])
    except Exception:
        pass
    return None


def is_our_app_process(pid):
    app_name = get_app_exe_name()
    try:
        result = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return app_name.lower() in result.stdout.lower()
    except Exception:
        return False


def kill_process(pid):
    try:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True, timeout=10,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception:
        return False


def find_and_kill_old_instance(port):
    if not is_port_in_use(port):
        return True
    print(f"Port {port} in use. Checking for old instance...")
    pid = find_pid_on_port(port)
    if pid is None:
        return False
    if not is_our_app_process(pid):
        print(f"  Port {port} held by another app (PID {pid}), skipping.")
        return False
    print(f"  Stopping old instance (PID {pid})...")
    kill_process(pid)
    for _ in range(10):
        time.sleep(0.5)
        if not is_port_in_use(port):
            return True
    return False


def find_available_port(start=DEFAULT_PORT):
    for port in range(start, MAX_PORT + 1):
        if not is_port_in_use(port):
            return port
    return start


def open_loading_page(port):
    """Open the loading page in the browser immediately.

    The page polls the server and auto-redirects once Waitress is up.
    """
    app_dir = get_app_dir()
    internal_dir = app_dir / '_internal' if is_frozen() else app_dir
    loading_path = internal_dir / "loading.html"

    if not loading_path.exists():
        loading_path = app_dir / "loading.html"

    if not loading_path.exists():
        return

    try:
        from version import __version__
        ver = __version__
    except Exception:
        ver = ""

    file_url = loading_path.as_uri() + f"?port={port}&v={ver}"
    webbrowser.open(file_url)


def open_browser_delayed(url, delay=2):
    def _open():
        time.sleep(delay)
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()


_shutdown_event = threading.Event()


def auto_backup(reason="startup"):
    """Run an automatic backup if configured. Never raises."""
    try:
        from backup.models import BackupSettings
        from backup.utils import sync_to_all_paths

        settings = BackupSettings.get()
        if not settings.auto_backup_enabled:
            return
        if not settings.local_backup_path and not settings.external_backup_path:
            return

        result = sync_to_all_paths(reason=reason)
        print(f"  {result}")
    except Exception as exc:
        print(f"  Auto-backup ({reason}) failed: {exc}")


def _periodic_backup_loop():
    """Background thread: backs up at the configured interval until shutdown."""
    while not _shutdown_event.is_set():
        try:
            from backup.models import BackupSettings
            settings = BackupSettings.get()
            interval_secs = max(3600, (settings.backup_interval_hours or 2) * 3600)
        except Exception:
            interval_secs = 7200  # 2-hour fallback

        if _shutdown_event.wait(timeout=interval_secs):
            break  # shutdown requested
        auto_backup(reason="periodic")


def start_periodic_backup_thread():
    """Start the background periodic-backup daemon thread."""
    t = threading.Thread(target=_periodic_backup_loop, daemon=True, name="periodic-backup")
    t.start()
    return t


def shutdown_backup():
    """Attempt a final backup on graceful shutdown (30s timeout)."""
    _shutdown_event.set()
    t = threading.Thread(target=auto_backup, kwargs={"reason": "shutdown"}, daemon=True)
    t.start()
    t.join(timeout=30)
    if t.is_alive():
        print("  Shutdown backup timed out -- skipping.")


def run_server(host='127.0.0.1', port=DEFAULT_PORT):
    from waitress import serve
    from django.core.wsgi import get_wsgi_application
    application = get_wsgi_application()
    app_name = get_app_exe_name()

    url = f'http://{host}:{port}/'
    print(f"\n{'='*50}")
    print(f"  {app_name}")
    print(f"{'='*50}")
    print(f"  Server: {url}")
    print(f"  Close this window to stop")
    print(f"{'='*50}\n")

    serve(application, host=host, port=port, threads=4)


def main():
    setup_logging()

    app_name = get_app_exe_name()
    print(f"Starting {app_name}...")

    data_dir = get_data_dir()
    if not acquire_lock(data_dir):
        print("Already running. Opening browser to existing instance...")
        port = find_running_instance_port()
        if port:
            webbrowser.open(f'http://127.0.0.1:{port}/')
        else:
            print("  Could not find the running instance's port.")
        _pause_if_debug("Already running. Press Enter to close...")
        sys.exit(0)

    # Determine port early so we can open the loading page immediately
    port = DEFAULT_PORT
    if not find_and_kill_old_instance(port):
        port = find_available_port(port + 1)
        print(f"Using fallback port {port}.")

    # Fix 1: Open loading page IMMEDIATELY so the user sees feedback instantly
    open_loading_page(port)

    # ensure_database() is synchronous — fast file copy, needed before Django starts
    install_type = ensure_database()

    print("Setting up Django...")
    setup_django()

    migrations_ok = run_migrations()
    if not migrations_ok:
        print("FATAL: Migrations failed. Cannot start server.")
        _pause_if_debug()
        sys.exit(1)

    create_superuser_if_needed()

    if install_type == "upgrade":
        sync_catalog_data()

    # Images are served on demand from the media pack zip (no extraction).
    # This background step just ensures the single zip is present in the data
    # dir; on a normal install the installer already copied it, so it's a no-op.
    def _media_pack_with_status():
        try:
            ensure_media_pack()
        finally:
            _clear_media_status()

    media_thread = threading.Thread(
        target=_media_pack_with_status, daemon=True, name="media-pack"
    )
    media_thread.start()

    # Fix 3: Delay startup backup by 30s so it doesn't block early requests
    def _delayed_startup_backup():
        time.sleep(30)
        auto_backup(reason="startup")

    threading.Thread(
        target=_delayed_startup_backup, daemon=True, name="delayed-backup"
    ).start()

    # Periodic background backups (layer 2)
    start_periodic_backup_thread()

    # Register signal handlers for graceful shutdown with final backup
    def _signal_handler(signum, frame):
        print(f"\nReceived signal {signum} -- shutting down (running final backup)...")
        shutdown_backup()
        print("Goodbye.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        run_server(port=port)
    except KeyboardInterrupt:
        print("\nShutting down (running final backup)...")
        shutdown_backup()
        print("Goodbye.")
    except Exception as e:
        print(f"\nServer error: {e}")
        import traceback
        traceback.print_exc()
        _pause_if_debug()
        sys.exit(1)


def _pause_if_debug(msg="Press Enter to close this window..."):
    if is_debug_exe() and is_frozen():
        try:
            print(f"\n{msg}")
            sys.__stdin__.readline()
        except Exception:
            pass


if __name__ == '__main__':
    try:
        main()
    except SystemExit as exc:
        if exc.code != 0:
            _pause_if_debug()
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            log_dir = get_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "crash.log", "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(f"Crash at {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        _pause_if_debug()
        sys.exit(1)
