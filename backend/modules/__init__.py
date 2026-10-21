"""
Module package compatibility helpers.

This repository historically imports backend modules via two paths:
- modules.<name>
- backend.modules.<name>

Expose both package names to the same module object to avoid duplicate imports
and patching inconsistencies in tests/runtime.
"""

import sys

if __name__ == "modules":
    sys.modules.setdefault("backend.modules", sys.modules[__name__])
elif __name__ == "backend.modules":
    sys.modules.setdefault("modules", sys.modules[__name__])
