#!/usr/bin/env python3
"""
resolve_specific.py — Resolve only specified events (faster than full sweep).
Usage: python3 resolve_specific.py public/live_events.json event-id-1 event-id-2 ...
       python3 resolve_specific.py public/live_events.json --all-sportex  (all with esportex wrapper)
"""
import sys
import json
import time
from pathlib import Path

# Reuse decoder from resolve_esportex_v3
sys.path.insert(0, str(Path(__file__).parent))
from resolve_esportex_v3 import decode_wrapper  # noqa


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    path = Path(sys.argv[1])
    root = json.loads(path.read_text())
    events = root.get("events") if isinstance(root, dict) else root
    if events is None:
        events = []

    if sys.argv[2] == "--all-sportex":
        targets = [ev for ev in events if isinstance(ev, dict) and any(
            isinstance(s, dict) and (s.get("url") or "").startswith("https://streams.esportex.site/player")
            for s in (ev.get("stream_servers") or [])
        )]
    else:
        target_ids = set(sys.argv[2:])
        targets = [ev for ev in events if isinstance(ev, dict) and ev.get("id") in target_ids]

    print(f"Targeting {len(targets)} event(s)")

    resolved = failed = 0
    for ev in targets:
        ev_id = ev.get("id", "?")
        title = ev.get("title", "?")
        servers = ev.get("stream_servers") or []
        print(f"\n[{ev_id}] {title} — {len(servers)} server(s)")
        for s in servers:
            url = s.get("url") or ""
            if not url.startswith("https://streams.esportex.site/player"):
                continue
            r = decode_wrapper(url)
            if r.get("ok"):
                s["resolved_m3u8"] = r["m3u8_url"]
                s["resolved_type"] = r["type"]
                s["last_resolved_at"] = int(time.time())
                s["resolution_status"] = "ok"
                resolved += 1
                print(f"  [OK]   {s.get('server','?'):10} → {r['m3u8_url']}")
            else:
                s["resolution_status"] = f"fail: {r.get('error')}"
                s["last_resolved_at"] = int(time.time())
                failed += 1
                print(f"  [FAIL] {s.get('server','?'):10} → {r.get('error')}")
            time.sleep(0.3)

    path.write_text(json.dumps(root, indent=2, ensure_ascii=False))
    print(f"\nDone: {resolved} resolved, {failed} failed. JSON written.")


if __name__ == "__main__":
    main()