"""Attribution vectors (LD-PEC-004 Amendment 5, LD-PEC-009 §7): a command may carry
`issued_by`, which is recorded with it in its history record and on its COMMAND event, and
plays no part in physics.

    python tools/m5a_vectors.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_vectors import R, S, SPLITTER_PORTS, Vector, base_entries, kit, lot, machine, split_process, splitter_plant, tank  # noqa: E402

SHEET = {"origin": "https://sheet.example", "session": "s-1", "app_name": "Example Sheet"}
OPERATOR = {"origin": "https://operator.example", "session": "s-2"}
HOST = {"origin": "host"}


def attributed(v: Vector, t: int, by: dict | None, op: str, **args) -> None:
    v.cmd(t, op, **args)
    if by is not None:
        v.commands[-1]["issued_by"] = by


def v38() -> list[Vector]:
    """Three applications share a claim. The host builds the plant; a spreadsheet creates and
    starts the job; an operator throttles the machine, and its second command is rejected
    (an unknown machine). One command carries no attribution. Every COMMAND event carries the
    command's issued_by, and the history records it; a restore mid-run continues. The
    physics is that of the same commands without attribution (compare V-02a's plant)."""
    e = base_entries()
    e["processes"] = [split_process("split-flow", "FLOW")]
    e["machines"] = [machine("splitter", ["split-flow"], R(1, 1000), SPLITTER_PORTS)]
    e["buffers"] = [tank("tank", 10**9)]
    e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("tank-kit", "BUFFER", "tank")]
    v = Vector("V-38", "attribution", "Commands carry the application that issued them into the history",
               ["LD-PEC-004 A5", "LD-PEC-009 §7"], e,
               [lot("kits", "inventory", products={"splitter-kit": "1", "tank-kit": "3"}),
                lot("water-1", "water-tank", {"h2o-l": "100000"})])
    splitter_plant(v, 0, "split-flow")
    for c in v.commands:
        c["issued_by"] = HOST
    attributed(v, 0, SHEET, "CREATE_JOB", job_id="job-a", process="split-flow", machine_id="splitter-1", target_extent=40_000, priority=0)
    attributed(v, 0, SHEET, "START", job_id="job-a")
    v.advance(10 * S)
    attributed(v, 10 * S, OPERATOR, "SET_OPERATING_POLICY", machine_id="splitter-1", rate_setpoint=R(1, 2000))
    attributed(v, 10 * S, OPERATOR, "SET_OPERATING_POLICY", machine_id="no-such-machine", rate_setpoint=R(1, 2000))
    v.snapshot("mid")
    v.advance(20 * S)
    v.restore("mid")
    attributed(v, 10 * S, None, "SET_PRIORITY", job_id="job-a", priority=5)
    for t in (20 * S, 60 * S):
        v.advance(t)
    return [v]


def main() -> int:
    for v in v38():
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
