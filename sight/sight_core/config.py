from dataclasses import dataclass
from pathlib import Path
import os
import json
from .security import reject_links, safe_file


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: int = 8080
    model: str = ""  # Require an exact, owner-verified Ollama model tag.
    ollama_url: str = "http://127.0.0.1:11434"
    model_timeout: float = 120
    thinking: bool | None = None

    @classmethod
    def from_env(cls):
        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "SIGHT"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "sight"
        try:
            port = int(os.environ.get("SIGHT_PORT", "8080"))
        except ValueError:
            raise ValueError("SIGHT_PORT must be an integer port between 1024 and 65535") from None
        if not 1024 <= port <= 65535:
            raise ValueError("SIGHT_PORT must be between 1024 and 65535")
        data_dir = reject_links(Path(os.environ.get("SIGHT_DATA_DIR", base)).expanduser()).resolve()
        saved = {}
        settings = data_dir / "local-model.json"
        safe_file(settings)
        if settings.is_file():
            try:
                saved = json.loads(settings.read_text(encoding="utf-8"))
                if not isinstance(saved, dict) or not isinstance(saved.get("model", ""), str):
                    raise ValueError()
                if saved.get('thinking') is not None and type(saved['thinking']) is not bool:raise ValueError()
            except (ValueError, OSError):
                raise ValueError("Invalid local-model.json; repair the saved model setting") from None
        return cls(data_dir, port, os.environ.get("SIGHT_OLLAMA_MODEL", saved.get("model", "")), thinking=saved.get('thinking'))

    @property
    def origins(self):
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    @property
    def hosts(self):
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
