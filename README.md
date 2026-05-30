# intecular-client

A Python client library and command-line tool for Intecular smart outlets. It
talks to the device directly over its local network API, so there's no cloud in
the loop. This is an independent project, and it isn't affiliated with or
endorsed by Intecular.

## Install

```bash
uv pip install -e ".[dev]"        # library + CLI into the project venv
uv tool install --editable .      # or just the `intecular` command, globally
```

## Using the library

```python
import asyncio
from intecular_client import IntecularClient

async def main() -> None:
    async with IntecularClient("10.42.44.90") as client:
        print(await client.get_device_info())
        await client.set_outlet(1, True)

asyncio.run(main())
```

## Using the CLI

```bash
intecular default select     # discover, pick, and save a default device
intecular device info
intecular outlet on 1
intecular watch --us
intecular nightlight aura color 200 90
```

The first time you run a command without a saved device, the CLI scans the
network and lets you pick one.

## Documentation

The full API and CLI reference lives on the
[documentation site](https://tinkerborg.github.io/intecular-client/).

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest -q
```

## License

[MIT](LICENSE)
