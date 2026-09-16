"""Register and activate the CopilotAgent custom module in OpenEMR's modules table.

OpenEMR only loads a custom module's bootstrap when a row in `modules` has
mod_active = 1, and Manage Modules is a UI-only flow. This writes the same row
InstModuleTable::register() would, plus the matching module_acl_sections row.

Needed after a fresh install, a database rebuild, or a snapshot restore.

Usage (local):
    cd usecases
    .venv\\Scripts\\python ..\\scripts\\register_module.py

Usage (Railway):
    $env:OE_DB_VIA="railway"; $env:OE_DB_PASS="<openemr db password>"
    .venv\\Scripts\\python ..\\scripts\\register_module.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usecases"))
from conftest import db_query  # noqa: E402

MODULE_DIR = "oe-module-copilot-agent"
MODULE_NAME = "Clinical Co-Pilot Agent"
# ucwords(strtolower($directory)), matching what the Installer writes.
MODULE_UI_NAME = "Oe-module-copilot-agent"
MODULE_TYPE_CUSTOM = 0

existing = db_query(
    f"SELECT mod_id, mod_active FROM modules WHERE mod_directory = '{MODULE_DIR}'"
)
if existing:
    mod_id, active = existing[0][0], existing[0][1]
    if active == "1":
        print(f"already registered and active (mod_id={mod_id})")
    else:
        db_query(f"UPDATE modules SET mod_active = 1 WHERE mod_directory = '{MODULE_DIR}'")
        print(f"re-enabled existing registration (mod_id={mod_id})")
    sys.exit(0)

# The Installer derives both ids from the highest existing ACL section.
next_id = int(db_query("SELECT COALESCE(MAX(section_id), 0) + 1 FROM module_acl_sections")[0][0])

# directory, sql_version and acl_version are NOT NULL with no default, so they
# must be supplied even though a menu-only module leaves them empty.
db_query(
    "INSERT INTO modules SET "
    f"mod_id = {next_id}, mod_name = '{MODULE_NAME}', mod_active = 1, "
    f"mod_ui_name = '{MODULE_UI_NAME}', mod_relative_link = '{MODULE_DIR}/index.php', "
    f"mod_directory = '{MODULE_DIR}', directory = '', sql_version = '', acl_version = '', "
    f"type = {MODULE_TYPE_CUSTOM}, date = NOW()"
)
db_query(
    f"INSERT INTO module_acl_sections VALUES ({next_id}, '{MODULE_NAME}', 0, '{MODULE_DIR}', {next_id})"
)
print(f"registered and activated (mod_id={next_id})")

for row in db_query(
    f"SELECT mod_id, mod_name, mod_directory, mod_active FROM modules WHERE mod_directory='{MODULE_DIR}'"
):
    print(f"  {row}")
