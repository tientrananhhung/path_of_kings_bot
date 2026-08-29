"""Đọc/ghi cấu hình TOML -> dict lồng nhau, có validate tối thiểu."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import tomli_w

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


class Config:
    """Bọc 3 file TOML. Truy cập bằng đường dẫn có dấu chấm: cfg.get('web.port')."""

    FILES = {"app": "app.toml", "game": "game.toml", "ads": "ads.toml"}

    def __init__(self, config_dir: Path | None = None):
        self.dir = Path(config_dir or CONFIG_DIR)
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        for key, name in self.FILES.items():
            path = self.dir / name
            if not path.exists():
                raise FileNotFoundError(f"thiếu file cấu hình: {path}")
            with path.open("rb") as f:
                self.data[key] = tomllib.load(f)

    def save(self, key: str) -> None:
        path = self.dir / self.FILES[key]
        with path.open("wb") as f:
            tomli_w.dump(self.data[key], f)

    # --- truy cập ---
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    @property
    def app(self) -> dict:
        return self.data["app"]

    @property
    def game(self) -> dict:
        return self.data["game"]

    @property
    def ads(self) -> dict:
        return self.data["ads"]


def data_path(*parts: str) -> Path:
    p = DATA_DIR.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
