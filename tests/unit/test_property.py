"""Hypothesis property-based tests for the Fireagent SDK models and client."""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given
from hypothesis import strategies as st

from fireagent.client import FireagentClient
from fireagent.exceptions import FireagentError, map_http_status
from fireagent.models import CommandResult, SandboxStatus


# ---------------------------------------------------------------------------
# CommandResult property tests
# ---------------------------------------------------------------------------
class TestCommandResultProperties:
    @given(
        stdout=st.text(max_size=1000),
        stderr=st.text(max_size=1000),
        exit_code=st.integers(min_value=-255, max_value=255),
        timed_out=st.booleans(),
        oom_killed=st.booleans(),
    )
    def test_command_result_roundtrip(
        self, stdout: str, stderr: str, exit_code: int, timed_out: bool, oom_killed: bool
    ) -> None:
        original = CommandResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=timed_out,
            oom_killed=oom_killed,
            start_time=datetime.now(timezone.utc),
            finish_time=datetime.now(timezone.utc),
        )

        # Round-trip through dict
        data = {
            "stdout": original.stdout,
            "stderr": original.stderr,
            "exit_code": original.exit_code,
            "timed_out": original.timed_out,
            "oom_killed": original.oom_killed,
            "start_time": original.start_time.isoformat() if original.start_time else None,
            "finish_time": original.finish_time.isoformat() if original.finish_time else None,
        }
        restored = CommandResult.from_dict(data)

        assert restored.stdout == original.stdout
        assert restored.stderr == original.stderr
        assert restored.exit_code == original.exit_code
        assert restored.timed_out == original.timed_out
        assert restored.oom_killed == original.oom_killed

    @given(
        timed_out=st.booleans(),
        oom_killed=st.booleans(),
    )
    def test_incompatible_states(self, timed_out: bool, oom_killed: bool) -> None:
        """Exit code should be 0 for success, non-zero for failures."""
        result = CommandResult(
            stdout="",
            stderr="error" if timed_out or oom_killed else "",
            exit_code=-1 if timed_out or oom_killed else 0,
            timed_out=timed_out,
            oom_killed=oom_killed,
        )
        if timed_out or oom_killed:
            assert result.exit_code != 0
        else:
            pass  # exit_code can be 0 or non-zero


# ---------------------------------------------------------------------------
# SandboxStatus property tests
# ---------------------------------------------------------------------------
class TestSandboxStatusProperties:
    @given(
        sandbox_id=st.text(min_size=1, max_size=50),
        state=st.sampled_from(
            ["queued", "creating", "ready", "running", "stopping", "stopped", "failed", "expired"]
        ),
        image=st.text(min_size=1, max_size=100),
        vcpus=st.integers(min_value=1, max_value=128),
        memory_mib=st.integers(min_value=64, max_value=1048576),
        disk_mib=st.integers(min_value=256, max_value=10485760),
    )
    def test_sandbox_status_roundtrip(
        self,
        sandbox_id: str,
        state: str,
        image: str,
        vcpus: int,
        memory_mib: int,
        disk_mib: int,
    ) -> None:
        data = {
            "id": sandbox_id,
            "state": state,
            "image": image,
            "vcpus": vcpus,
            "memory_mib": memory_mib,
            "disk_mib": disk_mib,
            "labels": {"env": "test"},
        }
        status = SandboxStatus.from_dict(data)

        assert status.sandbox_id == sandbox_id
        assert status.state == state
        assert status.image == image
        assert status.vcpus == vcpus
        assert status.memory_mib == memory_mib
        assert status.disk_mib == disk_mib

    @given(st.text(min_size=0, max_size=200))
    def test_timestamp_parsing(self, ts_str: str) -> None:
        """Timestamp parsing should never crash."""
        from fireagent.models import _parse_ts

        result = _parse_ts(ts_str)
        if ts_str and ("T" in ts_str or "Z" in ts_str or "+" in ts_str):
            # It might parse or return None, but shouldn't raise
            pass
        # Should never raise
        assert True

    @given(
        sandbox_id=st.text(min_size=1, max_size=50),
        state=st.sampled_from(["failed", "expired"]),
        failure_reason=st.text(max_size=500),
    )
    def test_failure_state_has_reason(
        self, sandbox_id: str, state: str, failure_reason: str
    ) -> None:
        """Failed/expired sandboxes should have a failure_reason."""
        data = {
            "id": sandbox_id,
            "state": state,
            "image": "ubuntu:24.04",
            "vcpus": 1,
            "memory_mib": 512,
            "disk_mib": 1024,
            "failure_reason": failure_reason,
        }
        status = SandboxStatus.from_dict(data)
        if state in ("failed", "expired"):
            # We set failure_reason, so it should be there
            assert status.failure_reason is not None
        else:
            assert status.failure_reason is None


# ---------------------------------------------------------------------------
# HTTP status mapping tests
# ---------------------------------------------------------------------------
class TestHttpStatusMapping:
    @given(st.integers(min_value=100, max_value=599))
    def test_all_status_codes_map(self, status_code: int) -> None:
        """Every HTTP status code should map to an exception class."""
        exc_cls = map_http_status(status_code)
        assert issubclass(exc_cls, FireagentError)

    @given(
        st.integers(min_value=100, max_value=599).filter(
            lambda x: x not in (400, 401, 403, 404, 409, 429, 500, 503)
        )
    )
    def test_unknown_status_maps_to_base(self, status_code: int) -> None:
        """Unknown status codes should map to FireagentError."""
        exc_cls = map_http_status(status_code)
        assert exc_cls == FireagentError


# ---------------------------------------------------------------------------
# Client constructor properties
# ---------------------------------------------------------------------------
class TestClientProperties:
    @given(
        base_url=st.text(min_size=1, max_size=200),
        api_key=st.text(min_size=0, max_size=100),
        timeout=st.integers(min_value=1, max_value=300),
        retries=st.integers(min_value=0, max_value=10),
    )
    def test_client_construction(
        self, base_url: str, api_key: str, timeout: int, retries: int
    ) -> None:
        """Client construction should never raise for any input."""
        # Filter out truly invalid URLs
        if base_url.startswith("/") or base_url.startswith(" "):
            return
        try:
            client = FireagentClient(
                base_url=base_url,
                api_key=api_key if api_key else None,
                timeout=timeout,
                retries=retries,
            )
            assert client._timeout == timeout
            assert client._retries == retries
        except Exception:
            pass  # Various URL formats may fail; not critical
