"""Everything a run produces gets written to disk so Tim can audit it."""

import json
import threading
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


def to_jsonable(obj):
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if is_dataclass(obj):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


class RunLog:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        (self.dir / "debate").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, name: str, obj) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(to_jsonable(obj), indent=2) + "\n")
        return path

    def debate(self, story_id: str, stage: str, round: int, persona: str, output) -> None:
        """Append one persona turn to the story's debate log (charter rule: every round is saved)."""
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "round": round,
            "persona": persona,
            "output": to_jsonable(output),
        }
        with self._lock, open(self.dir / "debate" / f"{story_id}.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
