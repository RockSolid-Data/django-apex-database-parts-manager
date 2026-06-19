"""
Build-time app identity registration and collision check.
Ensures no two projects share an app_key, app_name, or display_name.
"""
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
IDENTITY_FILE = PROJECT_DIR / ".app_identity"
REGISTRY_FILE = PROJECT_DIR.parent / ".app_registry.json"


def load_identity():
    if not IDENTITY_FILE.exists():
        print(f"[ERROR] .app_identity not found in {PROJECT_DIR}")
        print("        Run the project scaffolding step first.")
        sys.exit(1)
    return json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))


def load_registry():
    if not REGISTRY_FILE.exists():
        return {"schema_version": 1, "entries": []}
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def save_registry(registry):
    REGISTRY_FILE.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def check_and_register():
    identity = load_identity()
    registry = load_registry()
    entries = registry.get("entries", [])

    my_key = identity["app_key"]
    my_name = identity["app_name"]
    my_display = identity["display_name"]
    my_dir = PROJECT_DIR.name

    for entry in entries:
        if entry.get("project_dir") == my_dir:
            # This is us -- update in place
            entry.update(identity)
            entry["project_dir"] = my_dir
            save_registry(registry)
            print(f"[REGISTRY] Updated: {my_name} ({my_dir})")
            return

        # Collision checks against OTHER projects
        if entry.get("app_key") == my_key:
            print("[ERROR] app_key collision!")
            print(f"        Key '{my_key}' is already used by project '{entry.get('project_dir')}'.")
            print("        Generate a new UUID in .app_identity.")
            sys.exit(1)

        if entry.get("app_name") == my_name:
            print("[ERROR] app_name collision!")
            print(f"        Name '{my_name}' is already used by project '{entry.get('project_dir')}'.")
            print("        Each project must have a unique APP_NAME.")
            sys.exit(1)

        if entry.get("display_name") == my_display:
            print("[ERROR] display_name collision!")
            print(f"        Display name '{my_display}' is already used by project '{entry.get('project_dir')}'.")
            print("        Each project must have a unique APP_DISPLAY_NAME (shortcuts would collide).")
            sys.exit(1)

    # No collision -- register as new
    new_entry = dict(identity)
    new_entry["project_dir"] = my_dir
    entries.append(new_entry)
    registry["entries"] = entries
    save_registry(registry)
    print(f"[REGISTRY] Registered new project: {my_name} ({my_dir})")


if __name__ == "__main__":
    check_and_register()
