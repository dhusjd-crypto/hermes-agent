"""Local lifecycle bridge for a remotely executed Kanban task.

The dispatcher launches this module as a detached child just like a local
worker.  It waits on the registered peer outside the dispatch lock, then
commits the result to the originating board with the run-id CAS guard.
"""

from __future__ import annotations

import json
import os
import sys


def run() -> int:
    from hermes_cli import kanban_db as kb
    from hermes_cli.subcommands.peer import execute_kanban_task

    task_id = (os.environ.get("HERMES_KANBAN_TASK") or "").strip()
    target = (os.environ.get("HERMES_KANBAN_REMOTE_TARGET") or "").strip()
    if not task_id or not target:
        print("remote Kanban worker missing task or target", file=sys.stderr)
        return 2

    conn = kb.connect()
    try:
        task = kb.get_task(conn, task_id)
        if task is None or task.status != "running" or task.current_run_id is None:
            print(f"remote Kanban task {task_id} is not an active run", file=sys.stderr)
            return 1
        expected_run_id = int(task.current_run_id)
        context = kb.build_worker_context(conn, task_id)
    finally:
        conn.close()

    try:
        remote = execute_kanban_task(
            target,
            task_id=task_id,
            context=context,
        )
    except Exception as exc:
        # A non-zero child exit is intentionally handled by the dispatcher's
        # existing crash/retry circuit breaker on its next tick.
        print(f"remote Kanban execution failed: {exc}", file=sys.stderr)
        return 1

    conn = kb.connect()
    try:
        completed = kb.complete_task(
            conn,
            task_id,
            result=remote["summary"],
            summary=remote["summary"],
            metadata={
                "remote_executor": {
                    key: remote[key]
                    for key in ("protocol", "peer", "profile", "session_id")
                }
            },
            expected_run_id=expected_run_id,
        )
    finally:
        conn.close()
    if not completed:
        print(
            f"remote Kanban result rejected for stale run {task_id}/{expected_run_id}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(remote, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
