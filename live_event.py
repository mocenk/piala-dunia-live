#!/usr/bin/env python3
"""
Live Event Manager - CLI module for piala-dunia-live.

Refactored from live_event_bot.py (was: Telegram polling bot, conflicted with
@rizbugsbot gateway on same token). Now: pure CLI. Yor (Hermes agent) reads
`/liveevent ...` from Riz's chat, dispatches via subprocess, and forwards the
returned text to Telegram with parse_mode=Markdown.

Commands:
  python3 live_event.py help
  python3 live_event.py list
  python3 live_event.py add <channel> "<title>" "<category>" <YYYY-MM-DD> <HH:MM> <HH:MM>
  python3 live_event.py rm <id-prefix>
  python3 live_event.py clean

Output: human-readable text (Markdown), one block per command. Exit 0 on
success, exit 1 on usage error / git push failure. Logs go to live_event.log.
"""
import sys
import os
import re
import json
import shlex
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path("/home/home/projects/piala-dunia-live")
EVENTS_FILE = PROJECT_DIR / "public" / "live_events.json"
M3U_FILE = PROJECT_DIR / "public" / "piala_dunia.m3u"
GIT_BRANCH = "main"
LOG_FILE = PROJECT_DIR / "live_event.log"
WIB = timezone(timedelta(hours=7))


def log(msg: str):
    ts = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_events() -> dict:
    """Return normalized {'events': [...], 'last_updated': ...}.

    Handles two on-disk shapes:
      - array root: [{id, title, ...}, ...]
      - object root: {events: [...], last_updated: ...}
    """
    if not EVENTS_FILE.exists():
        return {"events": [], "last_updated": None}
    try:
        with open(EVENTS_FILE) as f:
            raw = json.load(f)
    except Exception as e:
        log(f"load_events error: {e}")
        return {"events": [], "last_updated": None}
    if isinstance(raw, list):
        return {"events": raw, "last_updated": None}
    if isinstance(raw, dict):
        raw.setdefault("events", [])
        raw.setdefault("last_updated", None)
        return raw
    return {"events": [], "last_updated": None}


def save_events(data: dict):
    data["last_updated"] = datetime.now(WIB).isoformat(timespec="seconds")
    with open(EVENTS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def git_push(message: str) -> tuple[bool, str]:
    """Commit + push. Returns (success, output)."""
    try:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        for cmd in [
            ["git", "-C", str(PROJECT_DIR), "add", "public/live_events.json"],
            ["git", "-C", str(PROJECT_DIR), "commit", "-m", message],
            ["git", "-C", str(PROJECT_DIR), "push", "origin", GIT_BRANCH],
        ]:
            r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
            if r.returncode != 0:
                return False, f"git {' '.join(cmd[1:])[:40]} failed: {r.stderr.strip() or r.stdout.strip()}"
        return True, "pushed"
    except Exception as e:
        return False, str(e)


def fetch_m3u_channels() -> list[dict]:
    """Parse M3U to get channel name + url list."""
    if not M3U_FILE.exists():
        return []
    channels = []
    cur = None
    try:
        text = M3U_FILE.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            comma = line.rfind(",")
            name = line[comma + 1:].strip() if comma >= 0 else ""
            cur = {"name": name, "url": ""}
        elif line and not line.startswith("#") and cur and not cur["url"]:
            cur["url"] = line
            channels.append(cur)
            cur = None
    return channels


def find_channel_by_keyword(keyword: str) -> list[dict]:
    """Return channels matching keyword (substring, case-insensitive). Max 8."""
    kw = keyword.lower().strip()
    if not kw:
        return []
    all_chs = fetch_m3u_channels()
    matches = [c for c in all_chs if kw in c["name"].lower()]
    return matches[:8]


def parse_date_time(date_str: str, time_str: str) -> datetime:
    """Parse YYYY-MM-DD + HH:MM -> datetime in WIB."""
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=WIB)


def generate_event_id(title: str, start: datetime) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:30].strip("-")
    return f"{slug}-{start.strftime('%Y%m%d-%H%M')}"


# === Sync command handlers (return Markdown text) ===

def cmd_help() -> str:
    return (
        "📺 *Live Event Manager* — `piala-dunia-live`\n\n"
        "*Commands:*\n"
        "`/liveevent list` — show active + future events\n"
        "`/liveevent add <channel> \"<title>\" \"<cat>\" <YYYY-MM-DD> <HH:MM> <HH:MM>`\n"
        "`/liveevent rm <id-prefix>` — remove event\n"
        "`/liveevent clean` — remove all past events\n\n"
        "*Examples:*\n"
        "`/liveevent add bein \"Argentina vs Brasil\" \"World Cup\" 2026-06-25 19:00 21:00`\n"
        "`/liveevent add rcti \"Persija vs Persib\" \"Liga 1\" 2026-06-21 15:30 17:30`\n\n"
        "*Notes:*\n"
        "• Timezone: WIB (Asia/Jakarta)\n"
        "• Channel keyword: substring match (case-insensitive)\n"
        "• Channel not found? Bot shows suggestions\n"
        "• Auto git push → Vercel redeploy ~30s\n"
        "• `/liveevent` sekarang invoke lewat Yor (gak ada polling bot terpisah)"
    )


def cmd_list() -> str:
    data = load_events()
    events = data.get("events", [])
    now = datetime.now(WIB)

    active = []
    future = []
    for ev in events:
        try:
            start = datetime.fromisoformat(ev["start"])
            end = datetime.fromisoformat(ev["end"])
        except Exception:
            continue
        if now < start:
            future.append((ev, start, end))
        elif start <= now < end:
            active.append((ev, start, end))

    if not active and not future:
        return "📭 *Belum ada event.*\n\nTambah: `/liveevent add ...`"

    lines = []
    if active:
        lines.append(f"🔴 *AKTIF ({len(active)})*\n")
        for ev, start, end in sorted(active, key=lambda x: x[1]):
            tstart = start.strftime("%H:%M")
            tend = end.strftime("%H:%M")
            mins_left = int((end - now).total_seconds() // 60)
            lines.append(
                f"• *{ev['title']}* — `{ev['id']}`\n"
                f"  📂 {ev.get('category', 'Live')}\n"
                f"  📺 {ev['channel_name']} • {tstart}–{tend} • ⏱ {mins_left}m left"
            )
    if future:
        lines.append(f"\n⏳ *AKAN DATANG ({len(future)})*\n")
        for ev, start, end in sorted(future, key=lambda x: x[1]):
            date_str = start.strftime("%d %b")
            tstart = start.strftime("%H:%M")
            tend = end.strftime("%H:%M")
            lines.append(
                f"• *{ev['title']}* — `{ev['id']}`\n"
                f"  📂 {ev.get('category', 'Live')}\n"
                f"  📺 {ev['channel_name']} • {date_str} {tstart}–{tend}"
            )

    return "\n".join(lines)


def cmd_add(channel_kw: str, title: str, category: str, date_str: str, tstart: str, tend: str) -> str:
    try:
        start_dt = parse_date_time(date_str, tstart)
        end_dt = parse_date_time(date_str, tend)
    except ValueError as e:
        return (
            f"❌ Format tanggal/waktu salah: `{e}`\n"
            f"Pakai: `YYYY-MM-DD HH:MM HH:MM` (24h, WIB)"
        )

    if end_dt <= start_dt:
        return "❌ End time harus setelah start time."
    if end_dt <= datetime.now(WIB):
        return (
            "⚠️ Event ini udah lewat (end time di masa lalu). Tetap ditambah? "
            "Tambah `/liveevent add ...` lagi dengan waktu valid."
        )

    matches = find_channel_by_keyword(channel_kw)
    if not matches:
        return (
            f"❌ Channel dengan keyword `{channel_kw}` gak ketemu di M3U.\n\n"
            f"Coba keyword lain. Contoh: `bein`, `espn`, `rcti`, `fifa`, `tvri`."
        )
    if len(matches) > 1:
        names = "\n".join(f"  • {c['name']}" for c in matches)
        return f"⚠️ Keyword `{channel_kw}`匹配 {len(matches)} channels:\n{names}\n\nPakai keyword lebih spesifik."

    ch = matches[0]
    event_id = generate_event_id(title, start_dt)

    data = load_events()
    data["events"] = [e for e in data["events"] if e.get("id") != event_id]
    data["events"].append({
        "id": event_id,
        "title": title,
        "category": category,
        "channel_name": ch["name"],
        "channel_url": ch["url"],
        "start": start_dt.isoformat(timespec="seconds"),
        "end": end_dt.isoformat(timespec="seconds"),
    })

    save_events(data)
    ok, msg = git_push(f"event: add {event_id}")
    if not ok:
        return f"⚠️ Event tersimpan lokal tapi git push gagal: `{msg}`\nCoba push manual atau cek git config."

    return (
        f"✅ *Event ditambah*\n\n"
        f"📺 *{title}*\n"
        f"📂 {category}\n"
        f"📡 {ch['name']}\n"
        f"⏰ {start_dt.strftime('%d %b %H:%M')}–{end_dt.strftime('%H:%M')} WIB\n"
        f"🆔 `{event_id}`\n\n"
        f"Git push OK → Vercel redeploy ~30s"
    )


def cmd_rm(prefix: str) -> str:
    if not prefix:
        return "❌ Usage: `/liveevent rm <id-prefix>`\nContoh: `/liveevent rm argentina-brasil`"

    prefix_lower = prefix.lower()
    data = load_events()
    matches = [e for e in data["events"] if e.get("id", "").lower().startswith(prefix_lower)]
    if not matches:
        return f"❌ Gak ada event dengan id prefix `{prefix}`.\nCek `/liveevent list`."
    if len(matches) > 1:
        names = "\n".join(f"  • `{e['id']}` — {e['title']}" for e in matches)
        return f"⚠️ Prefix `{prefix}`匹配 {len(matches)} events:\n{names}\n\nPakai prefix lebih panjang."

    target = matches[0]
    data["events"] = [e for e in data["events"] if e["id"] != target["id"]]
    save_events(data)
    ok, msg = git_push(f"event: rm {target['id']}")
    if not ok:
        return f"⚠️ Dihapus lokal tapi git push gagal: `{msg}`"
    return f"🗑️ Dihapus: *{target['title']}* (`{target['id']}`)"


def cmd_clean() -> str:
    data = load_events()
    now = datetime.now(WIB)
    before = len(data["events"])
    kept = []
    removed = []
    for ev in data["events"]:
        try:
            end = datetime.fromisoformat(ev["end"])
        except Exception:
            kept.append(ev)
            continue
        if end > now:
            kept.append(ev)
        else:
            removed.append(ev["title"])
    data["events"] = kept
    save_events(data)
    removed_count = before - len(kept)

    if removed_count == 0:
        return "✅ Gak ada event lewat. Bersih."

    ok, msg = git_push(f"event: clean {removed_count} past events")
    status = "✅" if ok else "⚠️"
    lines = "\n".join(f"  • {t}" for t in removed[:20])
    if len(removed) > 20:
        lines += f"\n  ... +{len(removed) - 20} more"
    return f"{status} *Dihapus {removed_count} event lewat:*\n{lines}\n\nGit: {msg}"


def dispatch_tokens(tokens: list) -> str:
    """Dispatch a pre-tokenized subcommand invocation. Returns Markdown reply.

    tokens: e.g. ['add', 'inews', 'Test Event', 'Cat', '2026-12-31', '19:00', '21:00']
            or ['list'], ['clean'], ['rm', 'some-id-prefix']
    """
    if not tokens:
        return cmd_help()
    sub = tokens[0].lower()
    rest = tokens[1:]

    if sub == "help":
        return cmd_help()
    if sub == "list":
        return cmd_list()
    if sub == "add":
        if len(rest) < 6:
            return (
                "❌ Format: `/liveevent add <channel> \"<title>\" \"<cat>\" <date> <HH:MM> <HH:MM>`\n\n"
                "Contoh: `/liveevent add bein \"Argentina vs Brasil\" \"World Cup\" 2026-06-25 19:00 21:00`"
            )
        channel_kw, title, category, date_str, tstart, tend = rest[:6]
        return cmd_add(channel_kw, title, category, date_str, tstart, tend)
    if sub in ("rm", "remove", "del", "delete"):
        prefix = rest[0] if rest else ""
        return cmd_rm(prefix)
    if sub == "clean":
        return cmd_clean()
    return f"❌ Subcommand `{sub}` gak dikenal.\nLihat: /liveevent help"


# Backwards-compat shim: dispatch from a raw string (used by older callers).
def dispatch(raw_args: str) -> str:
    """Dispatch from a raw subcommand string. shlex-splits it. Prefer
    dispatch_tokens() when the caller already has tokens to avoid quote loss."""
    s = (raw_args or "").strip()
    if not s:
        return cmd_help()
    try:
        return dispatch_tokens(shlex.split(s))
    except ValueError as e:
        return f"❌ Parse error: {e}\n\nLihat: /liveevent help"


def main():
    # Accept the full subcommand line as a single argv (shell preserves quotes),
    # then shlex-split it. Lets the agent (Yor) call us with quoted titles like:
    #   python3 live_event.py 'add inews "Test Event" "Cat" 2026-12-31 19:00 21:00'
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        text = cmd_help()
        print(text)
        return
    raw_line = sys.argv[1]
    try:
        tokens = shlex.split(raw_line)
    except ValueError as e:
        print(f"❌ Parse error: {e}\n\nLihat: /liveevent help")
        sys.exit(1)
    text = dispatch_tokens(tokens)
    print(text)
    if tokens:
        log(f"dispatch {tokens[0]} -> {len(text)} chars")


if __name__ == "__main__":
    main()
