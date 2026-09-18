# neolyrcs-py

Letras sincronizadas (karaoke) en la terminal para Linux.

## Requisitos

- Python 3.11+
- [`playerctl`](https://github.com/altdesktop/playerctl)
- [`uv`](https://docs.astral.sh/uv/) (recomendado) o `pip`

## Instalación

```bash
git clone https://github.com/albeiroigor/neolyrcs-py.git
cd neolyrcs-py
uv sync
```

## Uso

```bash
uv run neolyrcs-py
# o sin instalar el script:
uv run python -m neolyrcs_py
```

## Atajos

- `c` Configuración
- `q` Salir
- `m` Búsqueda manual

## Configuración

Ajusta color de acento, líneas visibles y reproductor manual. Guarda con `s`.

## Caché

Las letras se cachean en `~/.cache/neolyrcs-py/` por 15 días.

> Si vienes de la versión anterior (`neoplug-lyrics`), su caché en
> `~/.cache/neoplug-lyrics/` quedó obsoleta y puedes borrarla.

## Licencia

GPL-3.0
