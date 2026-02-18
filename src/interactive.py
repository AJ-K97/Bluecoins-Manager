"""Compatibility layer for interactive CLI entrypoints.

Interactive CLI implementation now lives under ``src.interactive_cli``.
"""

from src.interactive_cli import *  # noqa: F401,F403


if __name__ == "__main__":
    try:
        import asyncio

        asyncio.run(interactive_main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
