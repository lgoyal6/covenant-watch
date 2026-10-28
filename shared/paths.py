from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIXTURES = ROOT / "fixtures"

CACHE = DATA / "cache"  # shared, append-only, keyed by URL hash
CONTRACTS = DATA / "contracts"  # Laksh writes
ARTIFACTS = DATA / "artifacts"  # Dat writes
GROUNDTRUTH = DATA / "groundtruth"  # Dat writes
EVAL = DATA / "eval"  # Dat writes
UNIVERSE = DATA / "universe.json"  # Dat writes
