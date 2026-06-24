#!/usr/bin/env python3
"""
resolve_all_parallel.py — Parallel resolver for all esportex wrappers in live_events.json.

Uses ThreadPoolExecutor for parallel HTTP I/O. Target: 423 servers in ~10-20s.
"""
import json
import sys
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API_BASE = "https://data.esportex.site/api/data?id="
XOR_KEY = 0x5A
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": "https://streams.esportex.site/",
    "Origin": "https://streams.esportex.site",
    "Accept": "*/*",
}
TIMEOUT = 10
MAX_WORKERS = 12  # conservative — server-side seems OK with this


def decode_wrapper(wrapper_url: str) -> dict:
    if wrapper_url.startswith("https://streams.esportex.site/player"):
        if "#" not in wrapper_url:
            return {"ok": False, "error": "no hash"}
        hash_part = wrapper_url.split("#", 1)[1]
    elif wrapper_url.startswith("https://player.lapakstreaming.live/"):
        # URL format: https://player.lapakstreaming.live/?id=<base64hash>
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(wrapper_url).query)
        hash_part = (qs.get("id") or [""])[0]
        if not hash_part:
            return {"ok": False, "error": "no id query"}
    else:
        return {"ok": False, "error": "unsupported wrapper"}
    api_url = API_BASE + hash_part
    try:
        req = urllib.request.Request(api_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        decoded = bytes((b ^ XOR_KEY) & 0xFF for b in data)
        j = json.loads(decoded.decode("utf-8"))
        return {
            "ok": True,
            "id": j.get("id"),
            "type": j.get("type"),
            "m3u8_url": j.get("url"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}


def collect_targets(root: dict):
    """Yield (server_dict, wrapper_url) for every esportex wrapper that needs resolution."""
    events = root.get("events") if isinstance(root, dict) else root
    now = time.time()
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        for srv in ev.get("stream_servers") or []:
            if not isinstance(srv, dict):
                continue
            url = srv.get("url") or ""
            if not (
                url.startswith("https://streams.esportex.site/player")
                or url.startswith("https://player.lapakstreaming.live/")
            ):
                continue
            # Skip if recently resolved:
            #  - <5min for HLS with auth_key (signs/expires quickly)
            #  - <1h for everything else
            if srv.get("resolved_m3u8") and srv.get("last_resolved_at"):
                try:
                    age = now - float(srv["last_resolved_at"])
                    resolved_url = str(srv.get("resolved_m3u8", ""))
                    ttl = 300 if ("auth_key=" in resolved_url or "cdntoken=" in resolved_url) else 3600
                    if age < ttl:
                        continue
                except Exception:
                    pass
            yield srv, url


def main():
    if len(sys.argv) < 2:
        print("Usage: resolve_all_parallel.py <live_events.json>")
        sys.exit(1)
    path = Path(sys.argv[1])
    root = json.loads(path.read_text())

    targets = list(collect_targets(root))
    print(f"Targets: {len(targets)} wrapper URLs (parallel={MAX_WORKERS})")
    if not targets:
        print("Nothing to resolve.")
        return

    t0 = time.time()
    resolved = failed = 0
    failures = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_to_srv = {
            ex.submit(decode_wrapper, url): srv
            for srv, url in targets
        }
        for i, fut in enumerate(as_completed(future_to_srv), 1):
            srv = future_to_srv[fut]
            r = fut.result()
            now = int(time.time())
            srv["last_resolved_at"] = now
            if r.get("ok"):
                srv["resolved_m3u8"] = r["m3u8_url"]
                srv["resolved_type"] = r["type"]
                srv["resolution_status"] = "ok"
                resolved += 1
            else:
                srv["resolution_status"] = f"fail: {r.get('error')}"
                failed += 1
                failures.append((srv.get("server", "?"), r.get("error")))
            if i % 30 == 0:
                elapsed = time.time() - t0
                print(f"  [{i}/{len(targets)}] {resolved} ok / {failed} fail — {elapsed:.1f}s")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s: {resolved} resolved, {failed} failed")
    if failures:
        print("Sample failures:")
        for srv, err in failures[:5]:
            print(f"  - {srv}: {err}")

    path.write_text(json.dumps(root, indent=2, ensure_ascii=False))
    print(f"Written: {path}")


if __name__ == "__main__":
    main()