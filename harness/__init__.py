import os
from pathlib import Path

import yaml

home_dir: str | None = os.environ.get("LLVM_HARNESS_HOME_DIR")


def require_home_dir() -> str:
  """Return home_dir or exit if the environment is not set up."""
  if home_dir is None:
    print("Error: The llvm-harness environment has not been brought up.")
    exit(1)
  return home_dir


def load_yaml_config(subdir: str, filename: str) -> dict:
  """Load and parse a YAML config file relative to LLVM_HARNESS_HOME_DIR."""
  base = home_dir or "."
  return yaml.safe_load(Path(os.path.join(base, subdir, filename)).read_text())
