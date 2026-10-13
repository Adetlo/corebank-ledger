from __future__ import annotations

import json
import logging

from corebank.config import Settings
from corebank.domain.events import DomainEvent, EventDispatcher, JournalPosted, default_dispatcher
from corebank.logging import ConsoleFormatter, JsonFormatter, configure_logging, correlation_id_var


def test_settings_safe_summary_masks_credentials() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:s3cret@db.example.com:5432/ledger",  # type: ignore[arg-type]
        log_level="debug",
    )
    summary = settings.safe_summary()
    assert "s3cret" not in json.dumps(summary)
    assert summary["database"] == "postgresql+psycopg://db.example.com/ledger"
    assert settings.log_level == "DEBUG"
    assert "s3cret" not in repr(settings)


def test_json_formatter_includes_required_fields() -> None:
    token = correlation_id_var.set("cid-123")
    try:
        record = logging.LogRecord("corebank.test", logging.INFO, __file__, 1, "hello", (), None)
        record.extra_field = "x"  # type: ignore[attr-defined]
        payload = json.loads(JsonFormatter().format(record))
    finally:
        correlation_id_var.reset(token)
    assert payload["event"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "corebank.test"
    assert payload["correlation_id"] == "cid-123"
    assert payload["extra_field"] == "x"
    assert "timestamp" in payload


def test_console_formatter_and_configure() -> None:
    record = logging.LogRecord("corebank.test", logging.WARNING, __file__, 1, "warn", (), None)
    line = ConsoleFormatter().format(record)
    assert "WARNING" in line and "warn" in line
    configure_logging("INFO", "console")
    assert logging.getLogger().level == logging.INFO
    configure_logging("INFO", "json")


def test_event_dispatcher_isolates_failing_handlers() -> None:
    dispatcher = EventDispatcher()
    seen: list[DomainEvent] = []

    def bad(_: DomainEvent) -> None:
        raise RuntimeError("boom")

    dispatcher.subscribe(bad)
    dispatcher.subscribe(seen.append)
    event = JournalPosted(
        correlation_id="c",
        journal_entry_id=__import__("uuid").uuid4(),
        reference="R",
        currency="GBP",
        total_debits=__import__("decimal").Decimal("1"),
        posting_count=2,
    )
    dispatcher.publish(event)
    assert seen == [event]
    assert event.name == "JournalPosted"
    assert event.payload()["reference"] == "R"
    assert isinstance(event.payload()["journal_entry_id"], str)


def test_default_dispatcher_logs(caplog) -> None:  # type: ignore[no-untyped-def]
    dispatcher = default_dispatcher()
    with caplog.at_level(logging.INFO, logger="corebank.events"):
        dispatcher.publish(
            JournalPosted(
                correlation_id="c",
                journal_entry_id=__import__("uuid").uuid4(),
                reference="R",
                currency="GBP",
                total_debits=__import__("decimal").Decimal("1"),
                posting_count=2,
            )
        )
    assert any("JournalPosted" in r.getMessage() for r in caplog.records)
