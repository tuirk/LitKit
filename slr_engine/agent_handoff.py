"""Shared schema for external agent prompt handoff files.

These files are for Codex / Claude Code / similar harnesses that do not get
called by Python directly. The engine stages structured prompts to disk; the
external harness reads them, produces JSON outputs, and writes back to the
review batch / review file that the engine later commits.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "slr-engine-agent-prompt/v1"


def make_packet(
    *,
    stage: str,
    project_id: str,
    item: dict,
    prompt: dict,
    input_refs: dict | None = None,
    output: dict | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": stage,
        "project_id": project_id,
        "item": item,
        "input_refs": input_refs or {},
        "prompt": prompt,
        "output": output or {},
    }


def write_json(path: Path, packet: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, ensure_ascii=False)


def write_jsonl(path: Path, packets: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for packet in packets:
            f.write(json.dumps(packet, ensure_ascii=False) + "\n")


def load_packets(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        if path.suffix.lower() == ".jsonl":
            packets = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                packets.append(json.loads(line))
            return packets
        obj = json.load(f)
    if isinstance(obj, list):
        return obj
    return [obj]
