# invisoutlet

A Python client library and command-line tool for InvisOutlet smart outlets. It
talks to the device directly over its local network API, so there's no cloud in
the loop. This is an independent project, and it isn't affiliated with or
endorsed by InvisOutlet.

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

[MIT](LICENSE)
