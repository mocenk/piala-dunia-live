#!/usr/bin/env python3
"""
resolve_esportex_v3.py — Pure Python esportex wrapper decoder.

Reverse-engineered from https://streams.esportex.site/player#<hash>:
  1. URL fragment after `#` is the path hash (already base64 encoded).
  2. Fetch https://data.esportex.site/api/data?id=<fragment>
  3. XOR-decode response bytes with key 0x5A (constant computed from
     `_0x133513 = -0x1308*0x1 + 0x6ca + 0xc98 = 90`).
  4. JSON.parse → { id, type, url } where url is the real m3u8/mpd link.

No browser. No VPS-IP captcha. No anti-iframe. Just HTTPS GET.
"""
import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

API_BASE = "https://data.esportex.site/api/data?id="
XOR_KEY = 0x5A  # 90 — _0x133513 = -0x1308 + 0x6ca + 0xc98
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": "https://streams.esportex.site/",
    "Origin": "https://streams.esportex.site",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}


def decode_wrapper(wrapper_url: str, timeout: int = 12) -> dict:
    """
    Given full wrapper URL like 'https://streams.esportex.site/player#c20vdm9saTI%3D',
    fetch the real stream URL.

    Returns dict {ok, m3u8_url, type, id, raw, error}.
    """
    if "#" not in wrapper_url:
        return {"ok": False, "error": "no hash fragment in url"}

    hash_part = wrapper_url.split("#", 1)[1]
    # URL fragment is already percent-encoded (e.g. c20vdm9saTI%3D).
    # urllib.parse.quote on it would double-encode → wrong hash. Pass as-is.
    api_url = API_BASE + hash_part

    try:
        req = urllib.request.Request(api_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except Exception as e:
        return {"ok": False, "error": f"fetch failed: {e}"}

    # XOR decode each byte
    decoded = bytes((b ^ XOR_KEY) & 0xFF for b in data)

    try:
        j = json.loads(decoded.decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"json parse failed: {e}", "raw": decoded[:64].hex()}

    return {
        "ok": True,
        "id": j.get("id"),
        "type": j.get("type"),  # 'hls' | 'dash' | 'hls1' | 'dash1'
        "m3u8_url": j.get("url"),
    }


def resolve_in_live_events(events_path: Path, *, dry_run: bool = False) -> dict:
    """
    Walk live_events.json. For every stream_servers[].url that's an esportex wrapper
    (no resolved_m3u8 yet, or stale >1h), resolve it server-side via XOR-decoded API.

    Writes back the JSON. Returns summary {total, resolved, failed, skipped}.
    """
    root = json.loads(events_path.read_text())
    # Top-level can be array OR dict with .events key
    if isinstance(root, dict):
        events = root.get("events", [])
    else:
        events = root
        root = {"events": events}  # wrap for write-back

    total = 0
    resolved = 0
    failed = 0
    skipped = 0
    failures = []

    for ev in events:
        if not isinstance(ev, dict):
            continue
        servers = ev.get("stream_servers")
        if not isinstance(servers, list):
            skipped += 1
            continue

        for srv in servers:
            if not isinstance(srv, dict):
                continue
            url = srv.get("url") or ""
            if not isinstance(url, str) or not url.startswith("https://streams.esportex.site/player"):
                continue
            total += 1

            # Skip if already resolved and fresh (<1h old)
            if srv.get("resolved_m3u8") and srv.get("last_resolved_at"):
                try:
                    age = time.time() - float(srv["last_resolved_at"])
                    if age < 3600:
                        skipped += 1
                        continue
                except Exception:
                    pass

            result = decode_wrapper(url)
            if result.get("ok"):
                srv["resolved_m3u8"] = result["m3u8_url"]
                srv["resolved_type"] = result["type"]
                srv["last_resolved_at"] = int(time.time())
                srv["resolution_status"] = "ok"
                resolved += 1
            else:
                srv["resolution_status"] = f"fail: {result.get('error', 'unknown')}"
                srv["last_resolved_at"] = int(time.time())
                failed += 1
                failures.append((srv.get("name", "?"), result.get("error")))

            # Gentle rate limit
            time.sleep(0.3)

        if total % 20 == 0 and total > 0:
            print(f"  ...progress: {total} processed, {resolved} ok, {failed} failed")

    if not dry_run:
        events_path.write_text(json.dumps(root, indent=2, ensure_ascii=False))

    return {
        "total": total,
        "resolved": resolved,
        "failed": failed,
        "skipped": skipped,
        "failures": failures,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  resolve_esportex_v3.py <wrapper_url>")
        print("  resolve_esportex_v3.py --resolve-json <live_events.json> [--dry-run]")
        sys.exit(1)

    if sys.argv[1] == "--resolve-json":
        path = Path(sys.argv[2])
        dry = "--dry-run" in sys.argv
        summary = resolve_in_live_events(path, dry_run=dry)
        print()
        print("=" * 60)
        print(f"Total:    {summary['total']}")
        print(f"Resolved: {summary['resolved']}")
        print(f"Failed:   {summary['failed']}")
        print(f"Skipped:  {summary['skipped']}")
        if summary["failures"]:
            print("\nFailures:")
            for title, err in summary["failures"]:
                print(f"  - {title}: {err}")
        sys.exit(0)

    # Single URL test
    result = decode_wrapper(sys.argv[1])
    print(json.dumps(result, indent=2))