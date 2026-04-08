"""
Apex Database - Desktop App Launcher
Entry point for the frozen application.
"""

import os
import sys
import time
import shutil
import socket
import msvcrt
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
    return "ApexDatabase"


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


def sync_catalog_data():
    """Sync new catalog records from the bundled seed database."""
    app_dir = get_app_dir()
    internal_dir = app_dir / '_internal' if is_frozen() else app_dir
    seed_path = internal_dir / "seed.sqlite3"

    if not seed_path.exists():
        print("No seed database found -- skipping catalog sync.")
        return

    try:
        from django.core.management import call_command
        print("Syncing catalog data from seed...")
        call_command('sync_catalog', seed_db=str(seed_path), verbosity=1)
        print("Catalog sync complete.")
    except Exception as e:
        print(f"Catalog sync warning: {e}")
        import traceback
        traceback.print_exc()


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


def open_browser_delayed(url, delay=2):
    def _open():
        time.sleep(delay)
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()


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

    open_browser_delayed(url)
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

    port = DEFAULT_PORT
    if not find_and_kill_old_instance(port):
        port = find_available_port(port + 1)
        print(f"Using fallback port {port}.")

    try:
        run_server(port=port)
    except KeyboardInterrupt:
        print("\nShutting down...")
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
