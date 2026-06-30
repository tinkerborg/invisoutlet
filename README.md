# invisoutlet

[![ci](https://github.com/tinkerborg/invisoutlet/actions/workflows/ci.yml/badge.svg)](https://github.com/tinkerborg/invisoutlet/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/tinkerborg/invisoutlet/graph/badge.svg)](https://codecov.io/gh/tinkerborg/invisoutlet)
[![docs](https://github.com/tinkerborg/invisoutlet/actions/workflows/docs.yml/badge.svg)](https://tinkerborg.github.io/invisoutlet/)
[![PyPI](https://img.shields.io/pypi/v/invisoutlet)](https://pypi.org/project/invisoutlet/)
[![Python](https://img.shields.io/pypi/pyversions/invisoutlet)](https://pypi.org/project/invisoutlet/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/tinkerborg/invisoutlet/blob/HEAD/LICENSE)

A Python client library and command-line tool for InvisOutlet smart outlets. It
talks to the device directly over its local network API, so there's no cloud in
the loop. This is an independent project, and it isn't affiliated with or
endorsed by InvisOutlet.

## Features

- **Local-only** — speaks the device's on-device WebSocket API directly; no
  cloud account, no internet dependency.
- **Push-driven** — subscribe to live sensor, outlet, and OTA updates as the
  device emits them; auto-reconnects with backoff.
- **Full device surface** — outlets, nightlight and Aura color arrays (static
  color/temperature, per-LED palettes, animated effects), sensor readings,
  configuration, accessory names, calibration, and OTA firmware updates.
- **Typed, async API** — `asyncio` throughout, parsed dataclass models, and
  exceptions on failure (no error codes to check).
- **`invis` CLI** — discover devices on the network and drive every command
  from the terminal.
- **Lightweight core** — the library depends only on `aiohttp` and `zeroconf`;
  CLI deps are an optional extra.

## Install

```bash
uv pip install -e ".[dev]"          # library + CLI + tests, into the project venv
uv tool install --editable ".[cli]" # or just the `invis` command, globally
```

The library itself only needs `aiohttp` and `zeroconf`; the `invis` CLI's
extra dependencies (`typer`, `rich`, `questionary`) live under the `cli` extra,
so embedding the library elsewhere stays lightweight.

## Using the library

```python
import asyncio
from invisoutlet import InvisOutletClient

async def main() -> None:
    async with InvisOutletClient("10.42.44.90") as client:
        print(await client.get_device_info())
        await client.set_outlet(1, True)

asyncio.run(main())
```

## Using the CLI

```bash
invis default select     # discover, pick, and save a default device
invis device info
invis outlet on 1
invis watch --us
invis nightlight aura color 200 90
```

The first time you run a command without a saved device, the CLI scans the
network and lets you pick one.

## Documentation

The full API and CLI reference lives on the
[documentation site](https://tinkerborg.github.io/invisoutlet/).

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest -q
```

## License

[MIT](https://github.com/tinkerborg/invisoutlet/blob/HEAD/LICENSE)
