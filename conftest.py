"""Repo-root pytest conftest: guarantees `import src...` works regardless of
which directory pytest is invoked from or how it auto-detects rootdir.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
