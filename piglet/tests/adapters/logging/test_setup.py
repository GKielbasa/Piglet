import json
from datetime import date
from pathlib import Path
from typing import Any

import structlog
from pydantic import SecretStr

from piglet.adapters.logging.setup import bind_run_id, configure_logging


def read_entries(log_dir: Path) -> list[dict[str, Any]]:
    log_file = log_dir / f"{date.today().isoformat()}.jsonl"
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]


def test_entry_lands_in_a_file_named_after_today(tmp_path: Path) -> None:
    configure_logging(tmp_path)

    structlog.get_logger().info("request_finished", duration_ms=12.5)

    assert (tmp_path / f"{date.today().isoformat()}.jsonl").exists()


def test_every_line_is_one_json_object_with_event_level_and_timestamp(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    logger = structlog.get_logger()

    logger.info("request_started", url="https://example.com")
    logger.warning("request_retried", attempt=2)

    entries = read_entries(tmp_path)
    assert [entry["event"] for entry in entries] == ["request_started", "request_retried"]
    assert [entry["level"] for entry in entries] == ["info", "warning"]
    assert all(entry["timestamp"] for entry in entries)


def test_run_id_appears_in_every_entry(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    run_id = bind_run_id()

    structlog.get_logger().info("request_started")
    structlog.get_logger().info("request_finished")

    assert [entry["run_id"] for entry in read_entries(tmp_path)] == [run_id, run_id]


def test_configured_secret_never_appears_literally(tmp_path: Path) -> None:
    configure_logging(tmp_path, secrets=[SecretStr("s3cr3t-key")])

    structlog.get_logger().info("request_started", url="https://example.com/data/s3cr3t-key/list.csv")

    raw_log = (tmp_path / f"{date.today().isoformat()}.jsonl").read_text(encoding="utf-8")
    assert "s3cr3t-key" not in raw_log
    assert read_entries(tmp_path)[0]["url"] == "https://example.com/data/***/list.csv"


def test_secretstr_passed_as_a_field_is_written_masked(tmp_path: Path) -> None:
    configure_logging(tmp_path)

    structlog.get_logger().info("client_built", api_key=SecretStr("s3cr3t-key"))

    raw_log = (tmp_path / f"{date.today().isoformat()}.jsonl").read_text(encoding="utf-8")
    assert "s3cr3t-key" not in raw_log
    assert "**********" in raw_log


def test_an_empty_secret_does_not_redact_everything(tmp_path: Path) -> None:
    configure_logging(tmp_path, secrets=[SecretStr("")])

    structlog.get_logger().info("request_started", url="https://example.com")

    assert read_entries(tmp_path)[0]["url"] == "https://example.com"
