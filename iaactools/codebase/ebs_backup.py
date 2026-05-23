#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Thin launcher for EBS backups.
Makes 'iaactools' importable whether we run this file from the repo root
or from inside the 'iaactools/' folder, and whether the package is installed.
"""

import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
PKG_DIR = THIS_FILE.parent              # .../iaactools
REPO_ROOT = PKG_DIR.parent              # parent of 'iaactools'

# Ensure the parent-of-iaactools is on the path so `import iaactools...` works
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# Also add the package dir so a direct 'from ebs_backup_pkg...' fallback works
if str(PKG_DIR) not in sys.path:
    sys.path.insert(0, str(PKG_DIR))

try:
    # Preferred (installed or runnable from repo root)
    from iaactools.codebase.ebs_backup_pkg.main import main
except Exception:
    try:
        # Fallback (running this file from inside iaactools/codebase/)
        from ebs_backup_pkg.main import main
    except Exception as e:
        sys.stderr.write(
            "[FATAL] Could not import ebs_backup package.\n"
            f"  Search paths include:\n    - {REPO_ROOT}\n    - {PKG_DIR}\n"
            f"  Import error: {e}\n"
            "Hints:\n"
            "  • Run from the repo root, or\n"
            "  • `pip install -e .` to install the package, or\n"
            "  • Ensure both 'iaactools/codebase/__init__.py' and 'iaactools/codebase/ebs_backup_pkg/__init__.py' exist.\n"
        )
        sys.exit(2)

if __name__ == "__main__":
    main()
