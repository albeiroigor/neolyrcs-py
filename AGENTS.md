# AGENTS.md

Small single-package Python TUI: synced (karaoke) lyrics in the terminal (Linux-only).

## Structure

- `neolyrcs_py/tui.py` — entrypoint (`LyricsApp`, `main()`). Polling loops, lyric state, rendering, animations.
- `neolyrcs_py/core.py` — all I/O and pure logic: `playerctl` subprocess calls, lrclib.net fetch, `~/.cache/neolyrcs-py/` cache, LRC parsing (`parse_lrc`, `find_current_line`).
- `neolyrcs_py/windows.py` — `ConfigScreen`, `ManualLyricsScreen` modals.
- `neolyrcs_py/styles.tcss` — all styling, loaded via absolute `CSS_PATH` so it works installed (not CWD-dependent).
- `neolyrcs_py/__main__.py` — `python -m neolyrcs_py` shim.
- No test suite, no lint/typecheck/CI config.

## Commands

- Run: `uv run neolyrcs-py` (console script, after `uv sync`) or `uv run python -m neolyrcs_py`.
- Requires Python 3.11+, `playerctl` binary, and a playing MPRIS source — without it the app idles on "Esperando Reproduccion...". Never run the app itself to "verify" — it is fullscreen and blocks; verify with the commands below.
- Deps: `httpx>=0.27`, `textual>=0.60` only (`pyproject.toml`).
- Verify: `uv run python -c "import neolyrcs_py.tui, neolyrcs_py.windows"` plus inline asserts for pure functions (`parse_lrc`, `find_current_line`, `clear_title`, cache roundtrip). No network-dependent scripts in repo.

## Gotchas

- Packaging: hatchling wheel uses `packages = ["neolyrcs_py"]` (whole dir, incl. `.tcss`) plus `[project.scripts]`. Keep `CSS_PATH` absolute (`Path(__file__).parent`).
- Linux/`playerctl` only: `core._run_playerctl` returns `None` (not an exception) when the binary is missing, the command fails, or it exceeds `PLAYERCTL_TIMEOUT` (5s) — callers treat that as "no player".
- Polling: song every 2s, position every 0.15s (`SONG_POLL_INTERVAL`, `POSITION_POLL_INTERVAL` in `tui.py`). `poll_song` has a race guard — if the song changed during `_resolve_lyrics`, the stale result is discarded. Keep that pattern for any new async fetch.
- Position tick must stay cheap: `find_current_line(timestamps, ...)` takes the precomputed `self._lyric_times` list — do not rebuild timestamps per tick.
- `parse_lrc` supports multiple tags per line (`[00:01][00:05]texto`); keep that when touching it.
- `fetch_lyrics`: 404 = no retry; 200 with invalid/empty JSON = None; everything else retries with linear backoff up to `MAX_ATTEMPTS`.
- Cache: keyed by md5 of `artist|title` (lowercased), 15-day TTL (`CACHE_MAX_AGE`), silent `OSError` swallowing on save is intentional. Manual correction (`m`) saves under both the corrected and original dirty keys — preserve that. Old `~/.cache/neoplug-lyrics/` from the pre-rename app is obsolete.
- Titles are normalized with `clear_title` (strips `(…)`/`[…]` noise) before display and API lookup; always pass cleaned titles to `fetch_lyrics`.
- Animations are manual `Color.blend()` steps in `@work(exclusive=True)` workers, not TCSS `transition` (border is composite and won't animate via CSS). Search pulse must be stopped via `_stop_searching_pulse()` (cancels the worker), not a flag — a flag leaves a lagging opacity animation over cached results.
- `windows.py` constrains choices: `LINE_OPTIONS = [3, 5, 7]`, fixed `ACCENT_COLORS`, player `__auto__` sentinel = `manual_player=None`. `apply_config` re-renders with `center_index=None` and resets `last_line_index`.
