from pathlib import Path
from typing import TypeVar, Type, Optional
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LocalStorage:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path.home() / ".atlassian-cli"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "features").mkdir(exist_ok=True)
        (self.base_dir / "prds").mkdir(exist_ok=True)
        (self.base_dir / "plans").mkdir(exist_ok=True)
        (self.base_dir / "qa").mkdir(exist_ok=True)
        (self.base_dir / "adrs").mkdir(exist_ok=True)

    def save(self, model: BaseModel, collection: str) -> None:
        path = self.base_dir / collection / f"{model.id}.json"  # type: ignore[attr-defined]
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")

    def load(self, model_cls: Type[T], collection: str, id: str) -> Optional[T]:
        path = self.base_dir / collection / f"{id}.json"
        if not path.exists():
            return None
        return model_cls.model_validate_json(path.read_text(encoding="utf-8"))

    def list_all(self, model_cls: Type[T], collection: str) -> list[T]:
        dir_path = self.base_dir / collection
        return [
            model_cls.model_validate_json(f.read_text(encoding="utf-8"))
            for f in sorted(dir_path.glob("*.json"))
        ]

    def next_id(self, prefix: str, collection: str) -> str:
        dir_path = self.base_dir / collection
        existing = [f.stem for f in dir_path.glob(f"{prefix}-*.json")]
        nums = [int(s.split("-")[-1]) for s in existing if s.split("-")[-1].isdigit()]
        return f"{prefix}-{(max(nums, default=0) + 1):03d}"
