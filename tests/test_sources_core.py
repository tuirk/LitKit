from litkit.store import ProjectConfig
from pathlib import Path


def test_sources_core_default_off():
    cfg = ProjectConfig.load(Path("projects/_example"))
    assert cfg.sources.get("core") is False or cfg.sources.get("core") is None
