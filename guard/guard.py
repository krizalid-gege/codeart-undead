#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "guard.json")


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_state():
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, STATE_PATH)


def age_days(value):
    dt = parse_iso(value)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def decide(state):
    timeline = state.get("timeline", {})
    rebuild_after = float(timeline.get("rebuildAfterDays", 5))
    reclaim_after = float(timeline.get("reclaimAfterDays", 7))
    anchor = timeline.get("lastRebuildAt") or timeline.get("createdAt")
    age = age_days(anchor)
    if age is None:
        return "REBUILD", {"reason": "no-baseline", "ageDays": None}
    if age >= rebuild_after:
        return "REBUILD", {"reason": "age-threshold", "ageDays": round(age, 2)}
    remaining = max(0.0, reclaim_after - age)
    return "HEARTBEAT", {"reason": "within-window", "ageDays": round(age, 2), "daysUntilReclaim": round(remaining, 2)}


def emit(action, detail, state):
    payload = {
        "action": action,
        "detail": detail,
        "state": state,
        "now": now_iso(),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if action == "HEARTBEAT" else 10


def cmd_status(_args):
    state = load_state()
    action, detail = decide(state)
    return emit(action, detail, state)


def cmd_mark(args):
    state = load_state()
    sandbox = state.setdefault("sandbox", {})
    service = state.setdefault("service", {})
    timeline = state.setdefault("timeline", {})

    if args.session_id is not None:
        sandbox["sessionId"] = args.session_id
    if args.workspace_id is not None:
        sandbox["workspaceId"] = args.workspace_id
    if args.pool_type is not None:
        sandbox["poolType"] = args.pool_type
    if args.port is not None:
        service["port"] = int(args.port)
    if args.public_url is not None:
        service["publicUrl"] = args.public_url

    stamp = now_iso()
    if args.action == "heartbeat":
        timeline["lastHeartbeatAt"] = stamp
        if not timeline.get("lastRebuildAt") and not timeline.get("createdAt"):
            timeline["createdAt"] = stamp
    elif args.action == "rebuild":
        timeline["lastRebuildAt"] = stamp
        timeline["lastHeartbeatAt"] = stamp
        if not timeline.get("createdAt"):
            timeline["createdAt"] = stamp
    else:
        raise SystemExit("unknown action: %s" % args.action)

    save_state(state)
    print(json.dumps({"ok": True, "action": args.action, "at": stamp, "publicUrl": service.get("publicUrl", "")}, ensure_ascii=False))
    return 0


def main():
    parser = argparse.ArgumentParser(description="sandbox guard state machine")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status")
    p_status.set_defaults(func=cmd_status)

    p_mark = sub.add_parser("mark")
    p_mark.add_argument("--action", required=True, choices=["heartbeat", "rebuild"])
    p_mark.add_argument("--session-id")
    p_mark.add_argument("--workspace-id")
    p_mark.add_argument("--pool-type", choices=["persistent", "ephemeral"])
    p_mark.add_argument("--port", type=int)
    p_mark.add_argument("--public-url")
    p_mark.set_defaults(func=cmd_mark)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()