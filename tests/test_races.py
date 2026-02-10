"""
Tests for ctx.all() (join) and ctx.race() (select) with mixed task types,
including activity cooperative cancellation via is_cancelled().

Ported from duroxide-node/__tests__/races.test.js
"""

import json
import os
import time
import pytest

from dotenv import load_dotenv

from duroxide import (
    PostgresProvider,
    Client,
    Runtime,
    PyRuntimeOptions,
)

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SCHEMA = "duroxide_python_races"
RUN_ID = f"rc{int(time.time() * 1000):x}"


def uid(name):
    return f"{RUN_ID}-{name}"


@pytest.fixture(scope="module")
def provider():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    return PostgresProvider.connect_with_schema(db_url, SCHEMA)


def run_orchestration(provider, name, input, setup_fn, timeout_ms=10_000):
    client = Client(provider)
    runtime = Runtime(provider, PyRuntimeOptions(dispatcher_poll_interval_ms=50))
    setup_fn(runtime)
    runtime.start()
    try:
        instance_id = uid(name)
        client.start_orchestration(instance_id, name, input)
        return client.wait_for_orchestration(instance_id, timeout_ms)
    finally:
        runtime.shutdown(100)


# ─── ctx.all() with mixed task types ─────────────────────────────


class TestAllMixedTypes:
    def test_joins_activity_and_timer(self, provider):
        def setup(rt):
            rt.register_activity("Slow", lambda ctx, inp: f"done-{inp}")

            @rt.register_orchestration("AllActivityTimer")
            def all_act_timer(ctx, input):
                results = yield ctx.all([
                    ctx.schedule_activity("Slow", "work"),
                    ctx.schedule_timer(50),
                ])
                return results

        result = run_orchestration(provider, "AllActivityTimer", None, setup)
        assert result.status == "Completed"
        assert len(result.output) == 2
        act_val = result.output[0]["ok"]
        if isinstance(act_val, str):
            try:
                act_val = json.loads(act_val)
            except (json.JSONDecodeError, TypeError):
                pass
        assert act_val == "done-work"
        assert result.output[1]["ok"] is None

    def test_joins_activity_and_wait_event(self, provider):
        instance_id = uid("all-wait")
        client = Client(provider)
        runtime = Runtime(provider, PyRuntimeOptions(dispatcher_poll_interval_ms=50))

        runtime.register_activity("Quick", lambda ctx, inp: f"quick-{inp}")

        @runtime.register_orchestration("AllActivityWait")
        def all_act_wait(ctx, input):
            results = yield ctx.all([
                ctx.schedule_activity("Quick", "go"),
                ctx.wait_for_event("signal"),
            ])
            return results

        runtime.start()
        try:
            client.start_orchestration(instance_id, "AllActivityWait", None)
            time.sleep(0.5)
            client.raise_event(instance_id, "signal", {"msg": "hi"})
            result = client.wait_for_orchestration(instance_id, 10_000)

            assert result.status == "Completed"
            assert len(result.output) == 2
            act_val = result.output[0]["ok"]
            if isinstance(act_val, str):
                try:
                    act_val = json.loads(act_val)
                except (json.JSONDecodeError, TypeError):
                    pass
            assert act_val == "quick-go"
            evt_val = result.output[1]["ok"]
            if isinstance(evt_val, str):
                try:
                    evt_val = json.loads(evt_val)
                except (json.JSONDecodeError, TypeError):
                    pass
            assert evt_val == {"msg": "hi"}
        finally:
            runtime.shutdown(100)

    def test_joins_multiple_timers(self, provider):
        def setup(rt):
            @rt.register_orchestration("AllTimers")
            def all_timers(ctx, input):
                results = yield ctx.all([
                    ctx.schedule_timer(50),
                    ctx.schedule_timer(100),
                ])
                return results

        result = run_orchestration(provider, "AllTimers", None, setup)
        assert result.status == "Completed"
        assert len(result.output) == 2
        assert result.output[0]["ok"] is None
        assert result.output[1]["ok"] is None


# ─── ctx.race() with mixed task types ────────────────────────────


class TestRaceMixedTypes:
    def test_races_activity_vs_timer_activity_wins(self, provider):
        def setup(rt):
            rt.register_activity("Fast", lambda ctx, inp: f"fast-{inp}")

            @rt.register_orchestration("RaceActTimer")
            def race_act_timer(ctx, input):
                winner = yield ctx.race(
                    ctx.schedule_activity("Fast", "go"),
                    ctx.schedule_timer(60000),
                )
                return winner

        result = run_orchestration(provider, "RaceActTimer", None, setup)
        assert result.status == "Completed"
        assert result.output["index"] == 0
        val = result.output["value"]
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
        assert val == "fast-go"

    def test_races_timer_vs_activity_timer_wins_cooperative_cancel(self, provider):
        instance_id = uid("race-timer-act")
        client = Client(provider)
        runtime = Runtime(
            provider,
            PyRuntimeOptions(
                dispatcher_poll_interval_ms=50,
                worker_lock_timeout_ms=2000,
            ),
        )
        activity_cancelled = {"value": False}

        @runtime.register_activity("Glacial")
        def glacial(ctx, inp):
            # Cooperative cancellation: poll is_cancelled() instead of sleeping forever
            for _ in range(200):
                if ctx.is_cancelled():
                    activity_cancelled["value"] = True
                    return "cancelled"
                time.sleep(0.05)
            return "timeout"

        @runtime.register_orchestration("RaceTimerAct")
        def race_timer_act(ctx, input):
            winner = yield ctx.race(
                ctx.schedule_timer(50),
                ctx.schedule_activity("Glacial", "x"),
            )
            return winner

        runtime.start()
        try:
            client.start_orchestration(instance_id, "RaceTimerAct", None)
            result = client.wait_for_orchestration(instance_id, 15_000)

            assert result.status == "Completed"
            assert result.output["index"] == 0
            assert result.output["value"] == "null"

            # Wait for the cancellation signal to propagate
            for _ in range(60):
                if activity_cancelled["value"]:
                    break
                time.sleep(0.1)
            assert activity_cancelled["value"], "activity should have seen is_cancelled()"
        finally:
            runtime.shutdown(2000)

    def test_races_wait_event_vs_timer_event_wins(self, provider):
        instance_id = uid("race-wait")
        client = Client(provider)
        runtime = Runtime(provider, PyRuntimeOptions(dispatcher_poll_interval_ms=50))

        @runtime.register_orchestration("RaceWaitTimer")
        def race_wait_timer(ctx, input):
            winner = yield ctx.race(
                ctx.wait_for_event("approval"),
                ctx.schedule_timer(60000),
            )
            return winner

        runtime.start()
        try:
            client.start_orchestration(instance_id, "RaceWaitTimer", None)
            time.sleep(0.3)
            client.raise_event(instance_id, "approval", {"ok": True})
            result = client.wait_for_orchestration(instance_id, 10_000)

            assert result.status == "Completed"
            assert result.output["index"] == 0
            val = result.output["value"]
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
            assert val == {"ok": True}
        finally:
            runtime.shutdown(100)

    def test_races_two_timers_shorter_wins(self, provider):
        def setup(rt):
            @rt.register_orchestration("RaceTwoTimers")
            def race_two_timers(ctx, input):
                winner = yield ctx.race(
                    ctx.schedule_timer(50),
                    ctx.schedule_timer(60000),
                )
                return winner

        result = run_orchestration(provider, "RaceTwoTimers", None, setup)
        assert result.status == "Completed"
        assert result.output["index"] == 0
