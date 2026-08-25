import sys
from pathlib import Path

# Tests import `src.*`; the project has no packaging metadata yet.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
