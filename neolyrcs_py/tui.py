import asyncio
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Vertical
from textual.widgets import ProgressBar, Static
from textual import work

from neolyrcs_py.core import (
    clear_title,
    fetch_lyrics,
    find_current_line,
    get_active_player,
    get_cached_lyrics,
    get_current_song,
    get_duration,
    get_position,
    parse_lrc,
    save_to_cache,
)
from neolyrcs_py.windows import ConfigScreen, ManualLyricsScreen

# --- Configuracion por defecto ---------------------------------------------
DEFAULT_ACCENT = "#ffffff"
DEFAULT_VISIBLE_LINES = 5

# --- Intervalos de polling ---------------------------------------------------
SONG_POLL_INTERVAL = 2.0
POSITION_POLL_INTERVAL = 0.15

# --- Textos de la UI ---------------------------------------------------------
TEXT_WAITING = "Esperando Reproduccion..."
TEXT_SEARCHING = "Buscando letra..."
TEXT_NOT_FOUND = 'No se encontro la letra. Presiona "m" para buscar manualmente.'
TEXT_NO_LYRICS = "Letra no disponible"
TEXT_HINT = "[dim]q salir · c config · m corregir letra[/dim]"

# --- Animaciones ---------------------------------------------------------
# Nota de diseno: en vez de declarar "transition: border ..." en el .tcss,
# animamos el color a mano interpolando con Color.blend() paso a paso. El
# soporte de "transition" en CSS de Textual esta pensado para propiedades
# simples (color, opacity, offset); border es una propiedad compuesta y no
# vale la pena apostar a que el motor de CSS la anime igual. Con blend()
# tenemos control total y es igual de fluido.

# Linea activa: "flash" desde un color claro hacia el acento
FLASH_COLOR = "#ffffff"
FLASH_STEPS = 6
FLASH_STEP_DELAY = 0.035  # ~210ms en total

# Transicion de color al cambiar el acento (borde + barra de progreso)
ACCENT_TRANSITION_STEPS = 10
ACCENT_TRANSITION_STEP_DELAY = 0.02  # ~200ms en total

# Pulso de opacidad mientras se busca la letra
SEARCH_PULSE_LOW_OPACITY = 0.35
SEARCH_PULSE_HIGH_OPACITY = 1.0
SEARCH_PULSE_HALF_CYCLE = 0.6  # segundos por medio ciclo (subir o bajar)


# Logica de interfaz
class LyricsApp(App):
    TITLE = "neolyrcs-py"
    CSS_PATH = str(Path(__file__).parent / "styles.tcss")
    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("c", "open_config", "Config"),
        Binding("m", "open_manual_lyrics", "Manual"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(TEXT_WAITING, id="song_info")
            yield Static("", id="lyrics")
            yield ProgressBar(id="progress", total=100, show_eta=False)
            yield Static(TEXT_HINT, id="hint")

    def on_mount(self) -> None:
        # Estado de la reproduccion actual
        self.last_song: str | None = None
        self.current_player: str | None = None
        self.current_artist: str = ""
        self.current_title: str = ""
        self.duration: float | None = None

        # Estado de la letra
        self.current_lyrics: list[tuple[float, str]] = []
        # Timestamps precalculados: find_current_line los reutiliza en cada
        # tick de posicion sin reconstruir la lista (era O(n) por tick).
        self._lyric_times: list[float] = []
        self.has_synced_lyrics: bool = False
        self.last_line_index: int = -1
        self._search_pulse_worker = None

        # Ultima "ventana" de lineas dibujada (para poder re-renderizar solo
        # el color durante una animacion, sin recalcular todo de nuevo)
        self._window_start: int = 0
        self._window_lines: list[str] = []
        self._window_center: int | None = None

        # Preferencias del usuario (se editan desde ConfigScreen)
        self.accent: str = DEFAULT_ACCENT
        self.manual_player: str | None = None
        self.max_visible_lines: int = DEFAULT_VISIBLE_LINES
        self.visible_lines: int = DEFAULT_VISIBLE_LINES

        # Referencias a widgets
        self.info = self.query_one("#song_info", Static)
        self.lyrics_widget = self.query_one("#lyrics", Static)
        self.progress_bar = self.query_one("#progress", ProgressBar)

        self.set_interval(SONG_POLL_INTERVAL, self.poll_song)
        self.set_interval(POSITION_POLL_INTERVAL, self.poll_position)
        self.call_after_refresh(self._recalculate_visible_lines)

    # ------------------------------------------------------------------
    # Configuracion
    # ------------------------------------------------------------------
    def action_open_config(self) -> None:
        self.push_screen(
            ConfigScreen(self.accent, self.max_visible_lines, self.manual_player),
            callback=self.apply_config,
        )

    def apply_config(self, result: dict | None) -> None:
        if result is None:
            return

        old_accent = self.accent
        self.accent = result["accent"]
        self.max_visible_lines = result["visible_lines"]
        self.manual_player = result["manual_player"]

        self._recalculate_visible_lines()
        if old_accent != self.accent:
            self._animate_accent_change(old_accent, self.accent)

        self.last_line_index = -1
        self.update_display(center_index=None)

    @work(exclusive=True, group="accent_transition")
    async def _animate_accent_change(self, from_hex: str, to_hex: str) -> None:
        """Transiciona el borde de la app y el color de la barra de progreso
        desde el acento viejo hacia el nuevo, en vez de saltar de golpe."""
        from_color = Color.parse(from_hex)
        to_color = Color.parse(to_hex)
        box = self.query_one("#box")
        bar_widget = self.progress_bar.query_one("Bar")

        for step in range(ACCENT_TRANSITION_STEPS + 1):
            factor = step / ACCENT_TRANSITION_STEPS
            blended = from_color.blend(to_color, factor)
            box.styles.border = ("round", blended)
            bar_widget.styles.color = blended
            await asyncio.sleep(ACCENT_TRANSITION_STEP_DELAY)

    # ------------------------------------------------------------------
    # Layout / redibujado
    # ------------------------------------------------------------------
    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._recalculate_visible_lines)

    def _recalculate_visible_lines(self) -> None:
        available = max(1, self.lyrics_widget.size.height)
        new_visible_lines = min(available, self.max_visible_lines)
        if new_visible_lines == self.visible_lines:
            return
        self.visible_lines = new_visible_lines
        center = self.last_line_index if (self.has_synced_lyrics and self.last_line_index >= 0) else None
        self.update_display(center_index=center)

    # ------------------------------------------------------------------
    # Busqueda manual de letra
    # ------------------------------------------------------------------
    @work
    async def action_open_manual_lyrics(self) -> None:
        result = await self.push_screen_wait(
            ManualLyricsScreen(self.current_artist, self.current_title)
        )
        if result is None:
            return

        # Guardamos el nombre "sucio" original para poder cachear tambien bajo esa llave
        dirty_artist, dirty_title = self.current_artist, self.current_title

        artist = result["artist"]
        title = result["title"]
        self.current_artist = artist
        self.current_title = title

        self._show_searching()
        await asyncio.sleep(0)

        lyrics_data = await self._resolve_lyrics(
            artist, title, extra_cache_key=(dirty_artist, dirty_title)
        )
        self._apply_lyrics_data(lyrics_data)

    # ------------------------------------------------------------------
    # Polling del reproductor
    # ------------------------------------------------------------------
    async def poll_song(self) -> None:
        player = self.manual_player or get_active_player()
        if player is None:
            self.current_player = None
            return
        self.current_player = player

        song = get_current_song(player)
        if not song or song == self.last_song:
            return
        self.last_song = song
        self.last_line_index = -1
        self.current_lyrics = []
        self._lyric_times = []
        self.has_synced_lyrics = False

        artist, title = song.split("|", 1)
        title = clear_title(title)
        self.current_artist = artist
        self.current_title = title

        self.info.update(f"{artist} - {title}")
        self._show_searching()
        await asyncio.sleep(0)

        self.duration = get_duration(player)
        self.progress_bar.update(
            total=self.duration if self.duration is not None else 100,
            progress=0,
        )

        lyrics_data = await self._resolve_lyrics(artist, title)

        # Si mientras buscabamos la letra el usuario cambio de cancion,
        # descartamos este resultado para no pisar lo que ya se este mostrando.
        if song != self.last_song:
            return

        self._apply_lyrics_data(lyrics_data)

    async def poll_position(self) -> None:
        if self.current_player is None:
            return

        position = get_position(self.current_player)

        if position is not None and self.duration:
            self.progress_bar.update(total=self.duration, progress=position)

        if not self.has_synced_lyrics or not self.current_lyrics or position is None:
            return

        idx = find_current_line(self._lyric_times, position)
        if idx == self.last_line_index:
            return
        self.last_line_index = idx
        self.update_display(center_index=idx, animate=True)

    # ------------------------------------------------------------------
    # Letras: busqueda (cache + red) y aplicacion al estado
    # ------------------------------------------------------------------
    def _show_searching(self) -> None:
        self.lyrics_widget.update(TEXT_SEARCHING)
        self._search_pulse_worker = self._pulse_while_searching()

    def _stop_searching_pulse(self) -> None:
        """Corta el pulso de busqueda ya mismo. Antes esto se hacia poniendo
        un flag (self._searching = False) que el loop de abajo solo revisaba
        al despertar de su propio sleep (hasta SEARCH_PULSE_HALF_CYCLE
        segundos despues); si la letra ya estaba en cache y aparecia al
        instante, la animacion de opacidad hacia el valor bajo seguia
        corriendo igual y el texto se veia oscurecerse un momento despues de
        ya mostrarse. Cancelando el worker directamente evitamos ese retraso."""
        if self._search_pulse_worker is not None:
            self._search_pulse_worker.cancel()
            self._search_pulse_worker = None
        self.lyrics_widget.styles.animate(
            "opacity", value=1.0, duration=SEARCH_PULSE_HALF_CYCLE / 2, easing="in_out_cubic"
        )

    @work(exclusive=True, group="search_pulse")
    async def _pulse_while_searching(self) -> None:
        """Hace pulsar suavemente el texto de 'Buscando letra...' mientras
        esperamos la respuesta (de cache o de la red). Se corta desde afuera
        con _stop_searching_pulse(), que cancela este worker."""
        self.lyrics_widget.styles.opacity = SEARCH_PULSE_HIGH_OPACITY
        going_dim = True
        while True:
            target = SEARCH_PULSE_LOW_OPACITY if going_dim else SEARCH_PULSE_HIGH_OPACITY
            self.lyrics_widget.styles.animate(
                "opacity", value=target, duration=SEARCH_PULSE_HALF_CYCLE, easing="in_out_cubic"
            )
            going_dim = not going_dim
            await asyncio.sleep(SEARCH_PULSE_HALF_CYCLE)

    async def _resolve_lyrics(
        self,
        artist: str,
        title: str,
        extra_cache_key: tuple[str, str] | None = None,
    ) -> dict[str, str | None] | None:
        """Busca la letra en cache; si no esta, la trae de la red y la guarda."""
        lyrics_data = get_cached_lyrics(artist, title)
        if lyrics_data is None:
            lyrics_data = await fetch_lyrics(artist, title)
            if lyrics_data:
                save_to_cache(artist, title, lyrics_data)
                if extra_cache_key:
                    save_to_cache(*extra_cache_key, lyrics_data)
        return lyrics_data

    def _apply_lyrics_data(self, lyrics_data: dict[str, str | None] | None) -> None:
        self._stop_searching_pulse()

        if not lyrics_data:
            self.current_lyrics = []
            self._lyric_times = []
            self.has_synced_lyrics = False
            self.lyrics_widget.update(TEXT_NOT_FOUND)
            return

        synced_lyrics = lyrics_data.get("syncedLyrics")
        if synced_lyrics:
            self.current_lyrics = parse_lrc(synced_lyrics)
            self._lyric_times = [t for t, _ in self.current_lyrics]
            self.has_synced_lyrics = True
        else:
            self.has_synced_lyrics = False
            plain = lyrics_data.get("plainLyrics")
            self.current_lyrics = [(0.0, line) for line in plain.split("\n")] if plain else []
            self._lyric_times = [t for t, _ in self.current_lyrics]

        self.last_line_index = -1
        self.update_display(center_index=None)

    # ------------------------------------------------------------------
    # Render de las lineas visibles
    # ------------------------------------------------------------------
    def update_display(self, center_index: int | None = None, animate: bool = False) -> None:
        if not self.current_lyrics:
            self.lyrics_widget.update(TEXT_NO_LYRICS)
            return

        total = len(self.current_lyrics)
        if center_index is None:
            start = 0
            end = min(self.visible_lines, total)
        else:
            start = max(0, center_index - self.visible_lines // 2)
            end = min(total, start + self.visible_lines)
            if end - start < self.visible_lines:
                start = max(0, end - self.visible_lines)

        self._window_start = start
        self._window_lines = [self.current_lyrics[i][1] for i in range(start, end)]
        self._window_center = center_index

        if animate and center_index is not None:
            self._flash_active_line()
        else:
            self._render_lines(self.accent)

    def _render_lines(self, highlight_color: str) -> None:
        """Dibuja la ventana actual de lineas usando highlight_color para
        resaltar la linea activa. Separado de update_display para poder
        re-pintar solo el color durante una animacion, sin recalcular la
        ventana de lineas en cada frame."""
        lines = list(self._window_lines)
        while len(lines) < self.visible_lines:
            lines.append("")

        formatted = []
        for i, line in enumerate(lines):
            real_index = self._window_start + i
            if self._window_center is not None and real_index == self._window_center:
                formatted.append(f"[bold {highlight_color}]♪ {line} ♪[/bold {highlight_color}]")
            else:
                formatted.append(line)

        self.lyrics_widget.update("\n".join(formatted))

    @work(exclusive=True, group="line_flash")
    async def _flash_active_line(self) -> None:
        """Efecto 'especial' para la linea activa: aparece con un destello
        claro que se funde hacia el color de acento, en vez de cambiar de
        golpe. Si la linea vuelve a cambiar antes de terminar, esta
        animacion se cancela sola (exclusive=True) y arranca una nueva."""
        flash = Color.parse(FLASH_COLOR)
        target = Color.parse(self.accent)

        for step in range(FLASH_STEPS + 1):
            factor = step / FLASH_STEPS
            blended = flash.blend(target, factor)
            self._render_lines(blended.hex)
            await asyncio.sleep(FLASH_STEP_DELAY)


def main() -> None:
    LyricsApp().run()


if __name__ == "__main__":
    main()
