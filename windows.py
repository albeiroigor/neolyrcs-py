from textual.app import ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Select, Static, Input

from core import list_players

ACCENT_COLORS = [
    ("Rojo", "#cf0000"),
    ("Azul", "#007aff"),
    ("Verde", "#32d74b"),
    ("Amarillo", "#e8c101"),
    ("Morado", "#af52de"),
    ("Blanco", "#ffffff"),
]

LINE_OPTIONS = [3, 5, 7]

AUTO_PLAYER = "__auto__"


# Seccion de configuracion
class ConfigScreen(ModalScreen):
    BINDINGS = [
        Binding("s", "save", "Guardar"),
        Binding("escape", "cancel", "Cancelar"),
    ]

    def __init__(self, current_accent: str, current_lines: int, current_player: str | None):
        super().__init__()
        self.current_accent = current_accent
        self.current_lines = current_lines
        self.current_player = current_player

    def compose(self) -> ComposeResult:
        players = list_players()

        accent_options = [(name, hex_value) for name, hex_value in ACCENT_COLORS]
        lines_options = [(str(n), n) for n in LINE_OPTIONS]
        player_options = [("Auto (detectar)", AUTO_PLAYER)] + [(p, p) for p in players]

        # Un Select con allow_blank=False exige que "value" sea una de las
        # opciones listadas, o revienta al construirse. current_lines siempre
        # deberia venir de LINE_OPTIONS, pero lo validamos igual por si el
        # llamador pasa algo distinto. current_player puede referirse a un
        # reproductor que ya no esta corriendo (list_players() no lo va a
        # incluir), en ese caso caemos de vuelta a "Auto" en vez de crashear.
        safe_lines = self.current_lines if self.current_lines in LINE_OPTIONS else LINE_OPTIONS[0]
        safe_player = self.current_player if self.current_player in players else AUTO_PLAYER

        with Vertical(id="config_box", classes="modal_box"):
            yield Static("Color de acento")
            yield Select(
                accent_options,
                value=self.current_accent,
                id="accent_select",
                allow_blank=False,
            )

            yield Static("Lineas visibles")
            yield Select(
                lines_options,
                value=safe_lines,
                id="line_select",
                allow_blank=False,
            )

            yield Static("Reproductor")
            yield Select(
                player_options,
                value=safe_player,
                id="player_select",
                allow_blank=False,
            )

            yield Static("[dim]Presiona [b]s[/b] para guardar[/dim]", id="hint")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "accent_select":
            return
        self.query_one("#config_box").styles.border = ("round", Color.parse(str(event.value)))

    def action_save(self) -> None:
        accent = self.query_one("#accent_select", Select).value
        lines = self.query_one("#line_select", Select).value
        player_raw = self.query_one("#player_select", Select).value
        player = None if player_raw == AUTO_PLAYER else player_raw

        self.dismiss({"accent": accent, "visible_lines": lines, "manual_player": player})

    def action_cancel(self) -> None:
        self.dismiss(None)


class ManualLyricsScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancelar"),
    ]

    def __init__(self, current_artist: str, current_title: str):
        super().__init__()
        self.current_artist = current_artist
        self.current_title = current_title

    def compose(self) -> ComposeResult:
        with Vertical(id="manual_box", classes="modal_box"):
            yield Static("Corregir busqueda de letra")
            yield Static("Artista")
            yield Input(value=self.current_artist, id="artist_input")
            yield Static("Titulo")
            yield Input(value=self.current_title, id="title_input")
            yield Static("[dim]Presiona [b]Enter[/b] para buscar[/dim]", id="hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        artist = self.query_one("#artist_input", Input).value.strip()
        title = self.query_one("#title_input", Input).value.strip()
        if not artist or not title:
            return
        self.dismiss({"artist": artist, "title": title})

    def action_cancel(self) -> None:
        self.dismiss(None)
