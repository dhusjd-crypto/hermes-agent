"""First vertical slice of peer-backed Kanban execution."""

from __future__ import annotations

import subprocess

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
