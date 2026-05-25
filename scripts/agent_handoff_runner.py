#!/usr/bin/env python3
"""Validate and apply external-harness outputs for litkit-agent-prompt/v1.

Typical flow:
  1. Engine writes *_prompts.jsonl or *_prompt.json
  2. External harness produces JSON/JSONL responses
  3. Run this script to validate and write the outputs back to the staged
     batch/review file
  4. Run the existing commit command from the packet

Response file shapes accepted:

  JSON object for a single packet:
    {"response": {...}}

  JSONL for many packets:
    {"record_id": 123, "response": {...}}
    {"canonical_id": "rec_000123", "response": {...}}

The "response" wrapper is optional; top-level payload also works.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.agent_handoff import SCHEMA_VERSION, load_packets


VALID_DECISIONS = {"include", "exclude", "unsure"}
VALID_ROB = {"low", "some_concerns", "high", "unclear"}


class ValidationError(Exception):
    pass


def _load_jsonish(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        if path.suffix.lower() == ".jsonl":
            rows = []
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValidationError(
                        f"{path.name}: invalid JSON on line {lineno}: {e}"
                    ) from e
            return rows
        obj = json.load(f)
    if isinstance(obj, list):
        return obj
    return [obj]


def _response_payload(obj: dict) -> dict:
    if "response" in obj and isinstance(obj["response"], dict):
        return obj["response"]
    return obj


def _packet_key(packet: dict, fallback_index: int) -> tuple[str, str]:
    item = packet.get("item") or {}
    if item.get("record_id") is not None:
        return ("record_id", str(item["record_id"]))
    if item.get("canonical_id"):
        return ("canonical_id", str(item["canonical_id"]))
    return ("index", str(fallback_index))


def _response_key(obj: dict, fallback_index: int) -> tuple[str, str]:
    if obj.get("record_id") is not None:
        return ("record_id", str(obj["record_id"]))
    if obj.get("canonical_id"):
        return ("canonical_id", str(obj["canonical_id"]))
    item = obj.get("item") or {}
    if item.get("record_id") is not None:
        return ("record_id", str(item["record_id"]))
    if item.get("canonical_id"):
        return ("canonical_id", str(item["canonical_id"]))
    return ("index", str(fallback_index))


def _get_path(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise ValidationError(f"missing required field '{path}'")
        cur = cur[part]
    return cur


def _set_path(obj: dict, path: str, value):
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _validate_screening_response(payload: dict):
    decision = payload.get("decision")
    if decision not in VALID_DECISIONS:
        raise ValidationError(f"invalid decision: {decision!r}")
    if not isinstance(payload.get("reason"), str) or not payload.get("reason").strip():
        raise ValidationError("reason must be a non-empty string")
    if not isinstance(payload.get("criteria_hit"), list):
        raise ValidationError("criteria_hit must be a list")


def _validate_fulltext_response(payload: dict, require_quality: bool):
    llm_rec = payload.get("llm_recommendation")
    if not isinstance(llm_rec, dict):
        raise ValidationError("llm_recommendation must be an object")
    _validate_screening_response(llm_rec)
    if not isinstance(payload.get("extraction"), dict):
        raise ValidationError("extraction must be an object")
    if require_quality:
        quality = payload.get("quality")
        if not isinstance(quality, dict):
            raise ValidationError("quality must be an object")
        _validate_risk_of_bias(quality)


def _validate_quality_response(payload: dict):
    if not isinstance(payload.get("fields"), dict):
        raise ValidationError("fields must be an object")
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        raise ValidationError("quality must be an object")
    _validate_risk_of_bias(quality)


def _validate_risk_of_bias(quality: dict):
    rob = quality.get("risk_of_bias_overall")
    if rob not in VALID_ROB:
        raise ValidationError(
            f"risk_of_bias_overall must be one of {sorted(VALID_ROB)}"
        )
    if not isinstance(quality.get("risk_of_bias_notes"), str) or not quality.get("risk_of_bias_notes").strip():
        raise ValidationError("risk_of_bias_notes must be a non-empty string")
    domains = quality.get("risk_of_bias_domains")
    if domains is not None and not isinstance(domains, list):
        raise ValidationError("risk_of_bias_domains must be a list")


def _validate_vocab_response(payload: dict):
    for key in ("clusters", "dropped", "added_synonyms"):
        if key not in payload:
            raise ValidationError(f"missing required field '{key}'")
    if not isinstance(payload["clusters"], list):
        raise ValidationError("clusters must be a list")
    if not isinstance(payload["dropped"], list):
        raise ValidationError("dropped must be a list")
    if not isinstance(payload["added_synonyms"], list):
        raise ValidationError("added_synonyms must be a list")


def _validate_payload_for_packet(packet: dict, payload: dict):
    stage = packet.get("stage")
    if stage == "title_abstract_screening":
        _validate_screening_response(payload)
        return
    if stage == "full_text_screen_extract":
        require_quality = "quality" in (packet.get("output") or {}).get("fields", [])
        _validate_fulltext_response(payload, require_quality=require_quality)
        return
    if stage == "quality_assessment":
        _validate_quality_response(payload)
        return
    if stage == "vocabulary_curation":
        _validate_vocab_response(payload)
        return

    # Fallback: check required field paths only
    output = packet.get("output") or {}
    for field in output.get("fields", []):
        _get_path(payload, field)


def _merge_into_jsonl_target(target_path: Path, packets: list[dict], payloads: dict[tuple[str, str], dict]):
    rows = _load_jsonish(target_path)
    row_map: dict[tuple[str, str], dict] = {}
    for idx, row in enumerate(rows, 1):
        key = _response_key(row, idx)
        row_map[key] = row

    commit_commands: list[str] = []
    for idx, packet in enumerate(packets, 1):
        packet_key = _packet_key(packet, idx)
        payload = payloads[packet_key]
        row = row_map.get(packet_key)
        if row is None:
            raise ValidationError(
                f"target file {target_path} has no row matching {packet_key[0]}={packet_key[1]}"
            )
        for field in (packet.get("output") or {}).get("fields", []):
            _set_path(row, field, _get_path(payload, field))
        cmd = (packet.get("output") or {}).get("commit_command")
        if cmd and cmd not in commit_commands:
            commit_commands.append(cmd)

    suffix = target_path.suffix.lower()
    if suffix == ".jsonl":
        with open(target_path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
    return commit_commands


def _merge_into_json_target(target_path: Path, payload: dict, packet: dict):
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    cmd = (packet.get("output") or {}).get("commit_command")
    return [cmd] if cmd else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packets", required=True,
                    help="Prompt packet file (.json or .jsonl)")
    ap.add_argument("--responses", required=True,
                    help="Harness response file (.json or .jsonl)")
    ap.add_argument("--validate-only", action="store_true",
                    help="Validate only; do not write back to targets")
    args = ap.parse_args()

    packets_path = Path(args.packets).resolve()
    responses_path = Path(args.responses).resolve()
    if not packets_path.exists():
        raise SystemExit(f"Not found: {packets_path}")
    if not responses_path.exists():
        raise SystemExit(f"Not found: {responses_path}")

    packets = load_packets(packets_path)
    responses = _load_jsonish(responses_path)
    if not packets:
        raise SystemExit("No packets found")
    if not responses:
        raise SystemExit("No responses found")

    for idx, packet in enumerate(packets, 1):
        if packet.get("schema_version") != SCHEMA_VERSION:
            raise SystemExit(
                f"Packet #{idx} has unsupported schema_version: {packet.get('schema_version')!r}"
            )

    response_map: dict[tuple[str, str], dict] = {}
    for idx, response_obj in enumerate(responses, 1):
        key = _response_key(response_obj, idx)
        response_map[key] = _response_payload(response_obj)

    packet_keys = [_packet_key(packet, idx) for idx, packet in enumerate(packets, 1)]
    for key in packet_keys:
        if key not in response_map:
            raise SystemExit(f"Missing response for {key[0]}={key[1]}")

    for idx, packet in enumerate(packets, 1):
        key = _packet_key(packet, idx)
        try:
            _validate_payload_for_packet(packet, response_map[key])
        except ValidationError as e:
            raise SystemExit(f"{key[0]}={key[1]} failed validation: {e}") from e

    print(f"Validated {len(packets)} packet response(s) from {responses_path.name}")

    if args.validate_only:
        print("Validation only; no files written.")
        return

    targets = {}
    for packet in packets:
        output = packet.get("output") or {}
        target = output.get("write_back_to") or output.get("write_to")
        if not target:
            raise SystemExit("Packet missing output.write_back_to/write_to")
        targets.setdefault(str(target), []).append(packet)

    commit_commands: list[str] = []
    for target_str, target_packets in targets.items():
        target_path = Path(target_str)
        if target_packets[0].get("stage") == "vocabulary_curation":
            if len(target_packets) != 1:
                raise SystemExit("vocabulary_curation expects exactly one packet")
            key = _packet_key(target_packets[0], 1)
            cmds = _merge_into_json_target(target_path, response_map[key], target_packets[0])
        else:
            cmds = _merge_into_jsonl_target(target_path, target_packets, response_map)
        for cmd in cmds:
            if cmd and cmd not in commit_commands:
                commit_commands.append(cmd)
        print(f"Wrote validated output to {target_path}")

    if commit_commands:
        print()
        print("Next:")
        for cmd in commit_commands:
            print(f"  {cmd}")


if __name__ == "__main__":
    main()
