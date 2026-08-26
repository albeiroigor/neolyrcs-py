# Neoplug Lyrics

Letras sincronizadas (karaoke) en la terminal, detectando automáticamente lo que estés escuchando en Linux.

## Requisitos

- Python 3.11+
- [`playerctl`](https://github.com/altdesktop/playerctl) instalado en el sistema (usa MPRIS/D-Bus, solo Linux)
- [`uv`](https://docs.astral.sh/uv/) (recomendado) o `pip`

## Instalación

```bash
git clone https://github.com/albeiroigor/neoplug-lyrics.git
cd neoplug-lyrics
uv sync
```

## Uso

```bash
uv run python tui.py
```

La app detecta automáticamente el reproductor activo (Spotify, Chromium, VLC, etc.), busca la letra sincronizada en [lrclib.net](https://lrclib.net) y la muestra en modo karaoke, resaltando la línea actual.

### Atajos de teclado

| Tecla | Acción             |
|-------|--------------------|
| `c`   | Abrir configuración|
| `q`   | Salir              |
| `m`   | Busqueda manual    |

### Configuración

Desde el panel (`c`) puedes ajustar:

- Color de acento
- Cantidad de líneas visibles (3 / 5 / 7)
- Reproductor manual (en vez de detección automática)
- presiona tecla (`s`) para guardar

## Cache de letras

Las letras encontradas se guardan localmente en `~/.cache/neoplug-lyrics-module/` por 15 días, para evitar peticiones repetidas a la API.

## Licencia

GPL3
