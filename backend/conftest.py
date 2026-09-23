"""Pytest configuration.

`test_debug.py` and `test_reports_download.py` are script-style developer
utilities that execute at import time (they mutate the DB and touch the
filesystem directly) and are not collected/parameterized like normal tests.
Their logic is covered by the real suite in `app/tests/`, so we exclude them
from collection to keep `pytest` (run from backend/) green.
"""

collect_ignore = [
    "test_debug.py",
    "test_reports_download.py",
]
