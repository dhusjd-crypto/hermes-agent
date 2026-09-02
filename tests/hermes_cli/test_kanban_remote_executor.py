"""First vertical slice of peer-backed Kanban execution."""

from __future__ import annotations

import subprocess
import time
import urllib.error

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_remote_worker
from hermes_cli.subcommands import peer as peer_cmd

_ORIGINAL_CONNECT = kb.connect


def _isolate_kanban(tmp_path, monkeypatch):
    """Use the workspace temp root without tripping the live-root guard.

    This checkout itself lives below the captured Hermes root, so pytest's
    deny-list cannot distinguish its sandbox tempdir from production.  The
    explicit DB and Kanban-home paths below remain test-only.
    """
    db_path = tmp_path / "kanban.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path / "kanban-home"))
    monkeypatch.setattr(kb, "connect", _ORIGINAL_CONNECT)
    return db_path


def test_dispatch_accepts_remote_target_without_local_profile(
    tmp_path, monkeypatch,
):
    db_path = _isolate_kanban(tmp_path, monkeypatch)
    conn = kb.connect(db_path)
    try:
        task_id = kb.create_task(
            conn, title="remote research", assignee="peer:spark/researcher"
        )
        monkeypatch.setattr(
            "hermes_cli.profiles.profile_exists", lambda _name: False
        )
        result = kb.dispatch_once(conn, dry_run=True)
    finally:
        conn.close()

    assert result.spawned == [
        (task_id, "peer:spark/researcher", "")
    ]
    assert result.skipped_nonspawnable == []


def test_local_profile_dispatch_path_is_unchanged(tmp_path, monkeypatch):
    db_path = _isolate_kanban(tmp_path, monkeypatch)
    conn = kb.connect(db_path)
    seen = []
    try:
        task_id = kb.create_task(
            conn, title="local work", assignee="local-worker"
        )
        monkeypatch.setattr(
            "hermes_cli.profiles.profile_exists", lambda name: name == "local-worker"
        )

        def local_spawn(task, workspace, *, board=None):
            seen.append((task.id, task.assignee, workspace, board))
            return 4567

        result = kb.dispatch_once(conn, spawn_fn=local_spawn)
        current = kb.get_task(conn, task_id)
    finally:
        conn.close()

    assert len(result.spawned) == 1
    assert seen[0][0:2] == (task_id, "local-worker")
    assert current.status == "running"
    assert current.worker_pid == 4567


def test_default_spawn_routes_remote_target_to_bridge(tmp_path, monkeypatch):
    db_path = _isolate_kanban(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    conn = kb.connect(db_path)
    try:
        task_id = kb.create_task(
            conn, title="remote research", assignee="peer:spark/researcher"
        )
        task = kb.claim_task(conn, task_id)
    finally:
        conn.close()

    captured = {}

    class FakeProc:
        pid = 8123

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    assert kb._default_spawn(task, str(workspace)) == 8123
    assert captured["cmd"][1:] == ["-m", "hermes_cli.kanban_remote_worker"]
    assert captured["env"]["HERMES_KANBAN_REMOTE_TARGET"] == (
        "peer:spark/researcher"
    )
    assert captured["env"]["HERMES_KANBAN_TASK"] == task_id


def test_remote_bridge_commits_result_with_run_guard(tmp_path, monkeypatch):
    db_path = _isolate_kanban(tmp_path, monkeypatch)
    conn = kb.connect(db_path)
    try:
        task_id = kb.create_task(
            conn,
            title="remote research",
            body="Return evidence",
            assignee="peer:spark/researcher",
        )
        claimed = kb.claim_task(conn, task_id)
        run_id = claimed.current_run_id
    finally:
        conn.close()

    monkeypatch.setenv("HERMES_KANBAN_TASK", task_id)
    monkeypatch.setenv(
        "HERMES_KANBAN_REMOTE_TARGET", "peer:spark/researcher"
    )
    seen = {}

    def fake_execute(target, *, task_id, context, timeout=peer_cmd.DM_TIMEOUT_S):
        seen.update(target=target, task_id=task_id, context=context)
        return {
            "protocol": peer_cmd.KANBAN_PROTOCOL,
            "status": "completed",
            "peer": "spark",
            "profile": "researcher",
            "session_id": "remote-session-1",
            "summary": "Remote evidence collected.",
        }

    monkeypatch.setattr(peer_cmd, "execute_kanban_task", fake_execute)
    assert kanban_remote_worker.run() == 0

    conn = kb.connect(db_path)
    try:
        completed = kb.get_task(conn, task_id)
        run = conn.execute(
            "SELECT outcome, summary, metadata FROM task_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    assert completed.status == "done"
    assert completed.result == "Remote evidence collected."
    assert run["outcome"] == "completed"
    assert run["summary"] == "Remote evidence collected."
    assert "remote-session-1" in run["metadata"]
    assert seen["target"] == "peer:spark/researcher"
    assert "Return evidence" in seen["context"]


def test_remote_bridge_marks_transport_outage_on_active_run(tmp_path, monkeypatch):
    db_path = _isolate_kanban(tmp_path, monkeypatch)
    conn = kb.connect(db_path)
    try:
        task_id = kb.create_task(
            conn, title="remote outage", assignee="peer:spark/researcher"
        )
        claimed = kb.claim_task(conn, task_id)
        run_id = claimed.current_run_id
    finally:
        conn.close()

    monkeypatch.setenv("HERMES_KANBAN_TASK", task_id)
    monkeypatch.setenv(
        "HERMES_KANBAN_REMOTE_TARGET", "peer:spark/researcher"
    )

    def offline(*_args, **_kwargs):
        raise peer_cmd.PeerUnavailableError("connection refused")

    monkeypatch.setattr(peer_cmd, "execute_kanban_task", offline)
    assert kanban_remote_worker.run() == 1

    conn = kb.connect(db_path)
    try:
        marker = conn.execute(
            "SELECT run_id, payload FROM task_events "
            "WHERE task_id=? AND kind='remote_peer_unavailable'",
            (task_id,),
        ).fetchone()
        current = kb.get_task(conn, task_id)
    finally:
        conn.close()
    assert marker is not None
    assert marker["run_id"] == run_id
    assert "connection refused" in marker["payload"]
    assert current.status == "running"


def _exhaust_offline_remote_task(conn, task_id: str) -> None:
    claimed = kb.claim_task(conn, task_id)
    run_id = claimed.current_run_id
    assert run_id is not None
    assert kb.record_remote_peer_unavailable(
        conn,
        task_id,
        error="Peer is unreachable: connection refused",
        expected_run_id=run_id,
    )
    with kb.write_txn(conn):
        now = int(time.time())
        conn.execute(
            "UPDATE task_runs SET status='crashed', outcome='crashed', "
            "ended_at=? WHERE id=?",
            (now, run_id),
        )
        conn.execute(
            "UPDATE tasks SET status='ready', claim_lock=NULL, "
            "claim_expires=NULL, worker_pid=NULL, current_run_id=NULL "
            "WHERE id=?",
            (task_id,),
        )
        kb._append_event(
            conn, task_id, "crashed", {"error": "worker exited 1"}, run_id=run_id
        )
    assert kb._record_task_failure(
        conn,
        task_id,
        "worker exited 1",
        outcome="crashed",
        failure_limit=1,
    )
    assert kb.get_task(conn, task_id).status == "blocked"


def test_dispatch_revives_and_spawns_exhausted_task_when_peer_recovers(
    tmp_path, monkeypatch,
):
    db_path = _isolate_kanban(tmp_path, monkeypatch)
    conn = kb.connect(db_path)
    spawned = []
    try:
        task_id = kb.create_task(
            conn,
            title="remote recovery",
            assignee="peer:spark/researcher",
            max_retries=1,
        )
        claimed = kb.claim_task(conn, task_id)
        run_id = claimed.current_run_id
        assert run_id is not None
        assert kb.record_remote_peer_unavailable(
            conn,
            task_id,
            error="Peer is unreachable: connection refused",
            expected_run_id=run_id,
        )
        kb._set_worker_pid(conn, task_id, 8123)
        monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "0")
        monkeypatch.setattr(kb, "_pid_alive", lambda _pid: False)
        monkeypatch.setattr(peer_cmd, "probe_kanban_target", lambda target: True)

        # The first tick observes the dead bridge, exhausts the retry budget,
        # and blocks. Recovery candidates are intentionally probed before the
        # dispatch lock, so the newly blocked task is picked up next tick.
        first = kb.dispatch_once(
            conn,
            spawn_fn=lambda *_args, **_kwargs: pytest.fail("must block first"),
            failure_limit=1,
        )
        assert first.peer_recovered == []
        assert kb.get_task(conn, task_id).status == "blocked"

        result = kb.dispatch_once(
            conn,
            spawn_fn=lambda task, workspace, **_kw: spawned.append(task.id) or 8124,
            failure_limit=1,
        )
        current = kb.get_task(conn, task_id)
        events = kb.list_events(conn, task_id)
    finally:
        conn.close()

    assert result.peer_recovered == [task_id]
    assert spawned == [task_id]
    assert current.status == "running"
    assert current.consecutive_failures == 0
    assert any(event.kind == "peer_recovered" for event in events)


def test_dispatch_keeps_exhausted_remote_task_blocked_while_peer_is_offline(
    tmp_path, monkeypatch,
):
    db_path = _isolate_kanban(tmp_path, monkeypatch)
    conn = kb.connect(db_path)
    try:
        task_id = kb.create_task(
            conn, title="remote offline", assignee="peer:spark/researcher"
        )
        _exhaust_offline_remote_task(conn, task_id)
        monkeypatch.setattr(peer_cmd, "probe_kanban_target", lambda target: False)

        result = kb.dispatch_once(
            conn,
            spawn_fn=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
            failure_limit=1,
        )
        current = kb.get_task(conn, task_id)
    finally:
        conn.close()

    assert result.peer_recovered == []
    assert current.status == "blocked"


def test_dispatch_does_not_revive_ordinary_remote_failure(
    tmp_path, monkeypatch,
):
    """Only a proven transport outage may bypass the retry-limit block."""
    db_path = _isolate_kanban(tmp_path, monkeypatch)
    conn = kb.connect(db_path)
    try:
        task_id = kb.create_task(
            conn, title="remote application failure", assignee="peer:spark/researcher"
        )
        claimed = kb.claim_task(conn, task_id)
        run_id = claimed.current_run_id
        with kb.write_txn(conn):
            now = int(time.time())
            conn.execute(
                "UPDATE task_runs SET status='crashed', outcome='crashed', "
                "ended_at=? WHERE id=?",
                (now, run_id),
            )
            conn.execute(
                "UPDATE tasks SET status='ready', claim_lock=NULL, "
                "claim_expires=NULL, worker_pid=NULL, current_run_id=NULL "
                "WHERE id=?",
                (task_id,),
            )
            kb._append_event(
                conn,
                task_id,
                "crashed",
                {"error": "remote agent failed"},
                run_id=run_id,
            )
        assert kb._record_task_failure(
            conn,
            task_id,
            "remote agent failed",
            outcome="crashed",
            failure_limit=1,
        )
        monkeypatch.setattr(
            peer_cmd,
            "probe_kanban_target",
            lambda _target: pytest.fail("ordinary failures must not probe the peer"),
        )

        result = kb.dispatch_once(
            conn,
            spawn_fn=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
            failure_limit=1,
        )
        current = kb.get_task(conn, task_id)
    finally:
        conn.close()

    assert result.peer_recovered == []
    assert current.status == "blocked"
    assert current.consecutive_failures == 1


def test_peer_transport_failure_has_explicit_unavailable_type(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    with pytest.raises(peer_cmd.PeerUnavailableError):
        peer_cmd._request("http://peer.invalid/api/status", "key", timeout=1)
