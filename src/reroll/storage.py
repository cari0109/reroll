"""Reading and writing life.json."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from reroll.models import Repo

DEFAULT_FILE = "life.json"


class RepoError(Exception):
    pass


class RepoNotFound(RepoError):
    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} not found")
        self.path = path


class RepoCorrupt(RepoError):
    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"{path} is malformed: {detail}")
        self.path = path
        self.detail = detail


def load_repo(path: Path) -> Repo:
    if not path.exists():
        raise RepoNotFound(path)
    try:
        return Repo.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as e:
        raise RepoCorrupt(path, str(e)) from e


def save_repo(repo: Repo, path: Path) -> None:
    """Write to a temp file in the same directory, then atomically replace,
    so an interrupted write never corrupts the repo."""
    data = repo.model_dump_json(indent=2)
    fd, tmp = tempfile.mkstemp(dir=path.parent or Path("."), prefix=".life-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
