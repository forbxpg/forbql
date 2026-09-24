from __future__ import annotations

import json
from typing import TYPE_CHECKING

from forbql.audit import GENESIS, AuditLog, verify_log

if TYPE_CHECKING:
    from pathlib import Path


def record(log: AuditLog, sql: str):
    return log.append(
        principal="local",
        connection="bank",
        profile="analyst",
        policy_hash="sha256:x",
        sql=sql,
        executed_sql=sql,
        allowed=True,
        rules=(),
        rows=1,
        size=1,
        truncated=False,
        duration_ms=1,
        error_class=None,
        error_detail=None,
    )


def write_three(path: Path) -> list[str]:
    log = AuditLog(path)
    return [record(log, f"SELECT {n}").hash for n in range(3)]


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_records_chain_from_genesis(tmp_path: Path):
    path = tmp_path / "audit.jsonl"

    hashes = write_three(path)
    first = json.loads(lines(path)[0])

    assert first["previous"] == GENESIS
    assert [json.loads(line)["previous"] for line in lines(path)[1:]] == hashes[:2]
    assert verify_log(path).intact
    assert verify_log(path).records == 3


def test_a_new_writer_continues_the_chain(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    hashes = write_three(path)

    record(AuditLog(path), "SELECT 4")

    assert json.loads(lines(path)[3])["previous"] == hashes[2]
    assert verify_log(path).intact


def test_an_altered_record_is_found(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    write_three(path)
    content = lines(path)
    altered = json.loads(content[1])
    altered["rows"] = 999
    content[1] = json.dumps(altered)
    path.write_text("\n".join(content) + "\n", encoding="utf-8")

    result = verify_log(path)

    assert result.broken_at == 2
    assert result.reason == "record altered after it was written"


def test_a_removed_record_is_found(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    write_three(path)
    content = lines(path)
    path.write_text("\n".join([content[0], content[2]]) + "\n", encoding="utf-8")

    result = verify_log(path)

    assert result.broken_at == 2
    assert result.reason is not None
    assert "chain broken" in result.reason


def test_swapped_records_are_found(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    write_three(path)
    content = lines(path)
    path.write_text(
        "\n".join([content[1], content[0], content[2]]) + "\n",
        encoding="utf-8",
    )

    assert verify_log(path).broken_at == 1


def test_garbage_is_not_a_record(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    write_three(path)
    path.write_text(path.read_text(encoding="utf-8") + "not json\n", encoding="utf-8")

    result = verify_log(path)

    assert result.broken_at == 4
    assert result.records == 3
