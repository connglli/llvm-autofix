from pathlib import Path


def list_skills() -> list[Path]:
  skills_dir = Path(__file__).parent
  return [
    sk.resolve()
    for sk in skills_dir.iterdir()
    if sk.is_dir() and (sk / "SKILL.md").exists()
  ]
