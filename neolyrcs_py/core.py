import subprocess
import httpx
import re
import json
import hashlib
import time
from bisect import bisect_right
from pathlib import Path


CACHE_DIR = Path.home() / ".cache" / "neoplug-lyrics"
CACHE_MAX_AGE = 15 * 24 * 60 * 60
TITLE_NOISE_PATTERN = re.compile(r"\([^)]*\)|\[[^\]]*\]")


def _run_playerctl(args: list[str]) -> str | None:
    try:
        return subprocess.check_output(
            ["playerctl", *args],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_active_player() -> str | None:
    output = _run_playerctl(["-a", "metadata", "--format", "{{playerName}}|{{status}}"])
    if output is None:
        return None

    for line in output.splitlines():
        if "|" not in line:
            continue
        player, status = line.split("|", 1)
        if status == "Playing":
            return player
    return None


def clear_title(title: str) -> str:
    title = TITLE_NOISE_PATTERN.sub("", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def get_current_song(player: str | None = None) -> str | None:
    if player is None:
        player = get_active_player()
    if player is None:
        return None

    output = _run_playerctl([f"--player={player}", "metadata", "--format", "{{artist}}|{{title}}"])
    if output is None:
        return None
    song = output.strip()
    return song or None


def _cache_key(artist: str, title: str) -> str:
    normalized = f"{artist.lower().strip()}|{title.lower().strip()}"
    return hashlib.md5(normalized.encode()).hexdigest()


def _cache_path(artist: str, title: str) -> Path:
    return CACHE_DIR / f"{_cache_key(artist, title)}.json"


def get_cached_lyrics(artist: str, title: str) -> dict[str, str | None] | None:
    path = _cache_path(artist, title)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            entry = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    age = time.time() - entry.get("timestamp", 0)
    if age > CACHE_MAX_AGE:
        return None
    return {"syncedLyrics": entry.get("syncedLyrics"), "plainLyrics": entry.get("plainLyrics")}


def save_to_cache(artist: str, title: str, data: dict[str, str | None]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(artist, title)
    entry = {
        "timestamp": time.time(),
        "syncedLyrics": data.get("syncedLyrics"),
        "plainLyrics": data.get("plainLyrics"),
    }
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(entry, f)
    except OSError:
        pass


async def fetch_lyrics(artist: str, title: str) -> dict[str, str | None] | None:
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://lrclib.net/api/get",
                params={"artist_name": artist, "track_name": title},
                timeout=15,
            )
        except httpx.RequestError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            # La API respondio 200 pero el cuerpo no era JSON valido
            return None
        if not data:
            return None
        return {"syncedLyrics": data.get("syncedLyrics"), "plainLyrics": data.get("plainLyrics")}


LRC_PATTERN = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


def parse_lrc(raw_lyrics: str) -> list[tuple[float, str]]:
    lyrics = []
    for line in raw_lyrics.splitlines():
        match = LRC_PATTERN.match(line)
        if not match:
            continue
        minutes, seconds, text = match.groups()
        timestamp = int(minutes) * 60 + float(seconds)
        lyrics.append((timestamp, text.strip()))
    lyrics.sort(key=lambda item: item[0])
    return lyrics


def get_current_line(lyrics: list[tuple[float, str]], current_time: float) -> int:
    timestamps = [line[0] for line in lyrics]
    return max(0, bisect_right(timestamps, current_time) - 1)


def get_position(player: str | None = None) -> float | None:
    if player is None:
        player = get_active_player()
    if player is None:
        return None

    output = _run_playerctl([f"--player={player}", "position"])
    if output is None:
        return None
    try:
        return float(output.strip())
    except ValueError:
        return None


def get_duration(player: str | None = None) -> float | None:
    if player is None:
        player = get_active_player()
    if player is None:
        return None

    output = _run_playerctl([f"--player={player}", "metadata", "mpris:length"])
    if output is None:
        return None
    try:
        return float(output.strip()) / 1_000_000
    except ValueError:
        return None


def list_players() -> list[str]:
    output = _run_playerctl(["-l"])
    if output is None:
        return []
    return [p.strip() for p in output.splitlines() if p.strip()]
