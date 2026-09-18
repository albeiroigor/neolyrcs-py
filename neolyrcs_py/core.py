"""E/S y logica pura: estado de `playerctl`, cache, API de letras y parseo LRC."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import time
from bisect import bisect_right
from pathlib import Path

import httpx

APP_NAME = "neolyrcs-py"
CACHE_DIR = Path.home() / ".cache" / APP_NAME
CACHE_MAX_AGE = 15 * 24 * 60 * 60

LRCLIB_API_URL = "https://lrclib.net/api/get"
FETCH_TIMEOUT = 15.0
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.5  # espera 0.5s, 1.0s entre reintentos

PLAYERCTL_TIMEOUT = 5.0

TITLE_NOISE_PATTERN = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_WHITESPACE_PATTERN = re.compile(r"\s+")
LRC_TAG_PATTERN = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def _run_playerctl(args: list[str]) -> str | None:
    try:
        return subprocess.check_output(
            ["playerctl", *args],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=PLAYERCTL_TIMEOUT,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
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
            player = player.strip()
            if player:
                return player
    return None


def clear_title(title: str) -> str:
    title = TITLE_NOISE_PATTERN.sub("", title)
    return _WHITESPACE_PATTERN.sub(" ", title).strip()


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

    if time.time() - entry.get("timestamp", 0) > CACHE_MAX_AGE:
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
    """Trae la letra de lrclib.net con reintentos y backoff lineal.

    404 = la cancion no existe (no se reintenta). 200 con cuerpo no-JSON
    o vacio = sin letra. Cualquier otro fallo (red, 5xx, 429) se reintenta
    hasta MAX_ATTEMPTS.
    """
    async with httpx.AsyncClient() as client:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await client.get(
                    LRCLIB_API_URL,
                    params={"artist_name": artist, "track_name": title},
                    timeout=FETCH_TIMEOUT,
                )
            except httpx.RequestError:
                pass
            else:
                if response.status_code == 404:
                    return None
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except ValueError:
                        return None
                    if not data:
                        return None
                    return {
                        "syncedLyrics": data.get("syncedLyrics"),
                        "plainLyrics": data.get("plainLyrics"),
                    }
                # Otros estados (500, 429, ...): caer al reintento de abajo
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (attempt + 1))
    return None


def parse_lrc(raw_lyrics: str) -> list[tuple[float, str]]:
    """Parsea LRC. Soporta varias etiquetas por linea ([00:01][00:05]texto)."""
    lyrics = []
    for line in raw_lyrics.splitlines():
        tags = LRC_TAG_PATTERN.findall(line)
        if not tags:
            continue
        text = LRC_TAG_PATTERN.sub("", line).strip()
        for minutes, seconds in tags:
            timestamp = int(minutes) * 60 + float(seconds)
            lyrics.append((timestamp, text))
    lyrics.sort(key=lambda item: item[0])
    return lyrics


def find_current_line(timestamps: list[float], current_time: float) -> int:
    """Indice de la linea activa por biseccion. Recibe los timestamps ya
    extraidos para no reconstruir la lista en cada tick de posicion."""
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
