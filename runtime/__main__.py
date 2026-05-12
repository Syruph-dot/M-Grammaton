"""CLI 入口：python -m runtime [options]"""

from runtime.runtime import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())