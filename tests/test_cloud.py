"""The AWS pieces, checked without an AWS account.

Each test stands in a fake client for boto3, so this runs anywhere. What it
proves is the logic around the calls: when a download happens, what an
AgentCore invocation accepts, and what the closing-time schedule asks for.
"""

import json
import os
from datetime import datetime, timezone

import pytest

from src.bakery.cloud import agentcore_app, schedule, storage


# ── S3 ──────────────────────────────────────────────────────────────────────

class FakeS3:
    def __init__(self, stamp, body="{}\n"):
        self.stamp = stamp
        self.body = body
        self.downloads = 0

    def head_object(self, Bucket, Key):
        return {"LastModified": self.stamp}

    def download_file(self, bucket, key, target):
        self.downloads += 1
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(self.body)


def test_an_s3_path_is_split_into_bucket_and_key():
    assert storage.split("s3://till-exports/shop/bills.jsonl") == \
        ("till-exports", "shop/bills.jsonl")
    with pytest.raises(ValueError, match="full s3"):
        storage.split("s3://only-a-bucket")


def test_the_export_is_downloaded_once_and_again_only_when_it_changes(tmp_path):
    storage._last_checked.clear()
    uri = "s3://till-exports/bills.jsonl"
    old = datetime(2026, 9, 1, 19, 30, tzinfo=timezone.utc)
    client = FakeS3(old)

    first = storage.local_copy(uri, str(tmp_path), client=client, now=0)
    assert os.path.exists(first) and client.downloads == 1
    assert abs(os.path.getmtime(first) - old.timestamp()) < 1, \
        "the local copy must carry the object's time, or the cache key breaks"

    storage.local_copy(uri, str(tmp_path), client=client, now=120)
    assert client.downloads == 1, "an unchanged export was downloaded again"

    client.stamp = datetime(2026, 9, 2, 19, 30, tzinfo=timezone.utc)
    storage.local_copy(uri, str(tmp_path), client=client, now=240)
    assert client.downloads == 2, "a new export in the bucket was missed"


def test_s3_is_not_asked_on_every_page_load(tmp_path):
    storage._last_checked.clear()
    client = FakeS3(datetime(2026, 9, 1, tzinfo=timezone.utc))
    uri = "s3://till-exports/bills.jsonl"
    storage.local_copy(uri, str(tmp_path), client=client, now=0)

    class Refuse:
        def head_object(self, **kwargs):
            raise AssertionError("asked S3 again within the check interval")

    storage.local_copy(uri, str(tmp_path), client=Refuse(), now=10)


def test_the_shop_loads_through_s3_when_the_path_says_so(monkeypatch, tmp_path):
    from src.bakery.ops import state

    seen = {}

    def fake_copy(uri, cache_dir):
        seen["uri"] = uri
        local = tmp_path / "bills.jsonl"
        local.write_text("", encoding="utf-8")
        return str(local)

    monkeypatch.setattr(storage, "local_copy", fake_copy)
    path = state.ensure("s3://till-exports/bills.jsonl")
    assert seen["uri"] == "s3://till-exports/bills.jsonl"
    assert path == str(tmp_path / "bills.jsonl")


# ── AgentCore ───────────────────────────────────────────────────────────────

def test_agentcore_refuses_an_unknown_run_and_says_what_is_allowed():
    result = agentcore_app.handle({"kind": "dance"})
    assert result["ok"] is False
    assert "nightly" in result["kinds"]


def test_agentcore_needs_a_prompt_for_a_question():
    result = agentcore_app.handle({"kind": "asked"})
    assert result["ok"] is False and "prompt" in result["error"]


def test_agentcore_refuses_a_payload_that_is_not_an_object():
    assert agentcore_app.handle("nightly")["ok"] is False


def test_agentcore_hands_the_run_to_the_same_agent(monkeypatch):
    calls = {}

    def fake_run(kind, prompt=None):
        calls["kind"], calls["prompt"] = kind, prompt
        return {"kind": kind, "said": "Planned tomorrow.", "ledger": {}}

    monkeypatch.setattr(agentcore_app.runs, "with_agent", fake_run)
    result = agentcore_app.handle({"kind": "asked", "prompt": "How is today?"})
    assert result["ok"] is True and result["said"] == "Planned tomorrow."
    assert calls == {"kind": "asked", "prompt": "How is today?"}


def test_a_failed_run_is_reported_not_raised(monkeypatch):
    def broken(kind, prompt=None):
        raise RuntimeError("no model")

    monkeypatch.setattr(agentcore_app.runs, "with_agent", broken)
    result = agentcore_app.handle({"kind": "nightly"})
    assert result == {"ok": False, "kind": "nightly", "error": "no model"}


# ── EventBridge Scheduler ───────────────────────────────────────────────────

RUNTIME = "arn:aws:bedrock-agentcore:eu-west-1:123456789012:runtime/sonnabon"
ROLE = "arn:aws:iam::123456789012:role/sonnabon-scheduler"


def test_the_nightly_schedule_fires_after_closing_and_skips_monday():
    made = schedule.request("sonnabon-nightly", RUNTIME, ROLE,
                            schedule.NIGHTLY, "Europe/Paris", "nightly")
    assert made["ScheduleExpression"] == "cron(35 19 ? * TUE-SUN *)"
    assert made["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert made["Target"]["Arn"] == schedule.TARGET_ARN

    sent = json.loads(made["Target"]["Input"])
    assert sent["agentRuntimeArn"] == RUNTIME
    assert json.loads(sent["payload"]) == {"kind": "nightly"}


def test_a_schedule_without_real_arns_is_refused():
    with pytest.raises(ValueError, match="not an ARN"):
        schedule.request("x", "runtime", ROLE, schedule.NIGHTLY, "UTC", "nightly")


def test_creating_schedules_asks_for_nightly_and_weekly():
    class FakeScheduler:
        def __init__(self):
            self.names = []

        def create_schedule(self, **kwargs):
            self.names.append(kwargs["Name"])
            return {"ScheduleArn": "arn:aws:scheduler:::schedule/" + kwargs["Name"]}

    client = FakeScheduler()
    schedule.create(RUNTIME, ROLE, client=client)
    assert client.names == ["sonnabon-nightly", "sonnabon-weekly"]
