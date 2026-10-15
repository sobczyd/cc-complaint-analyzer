"""Assembling the client stack.

The order below is the whole design in five lines. Nothing else in the project knows
how the layers nest, so reordering or removing a behaviour is one edit here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..logs import RunLog
from ..run_paths import RunPaths
from ..settings import Credentials, Settings
from .cache import CachingClient, PassthroughClient
from .openai_compat import OpenAICompatibleClient
from .protocol import ChatClient
from .rate_limit import RateLimitedClient
from .recorder import RecordingClient
from .retry import RetryingClient


@dataclass
class ClientStack:
    """The assembled client plus the pieces a run wants to report on."""

    client: ChatClient
    cache: Any
    transport: Any

    @property
    def cache_hits(self) -> int:
        return getattr(self.cache, "hits", 0)

    @property
    def cache_misses(self) -> int:
        return getattr(self.cache, "misses", 0)

    async def aclose(self) -> None:
        closer = getattr(self.transport, "aclose", None)
        if closer is not None:
            await closer()


def build(
    settings: Settings,
    credentials: Credentials | None,
    run_paths: RunPaths,
    log: RunLog,
    *,
    transport: ChatClient | None = None,
) -> ClientStack:
    """Build the stack: cache -> retry -> rate limit -> recorder -> transport."""
    if transport is None:
        if credentials is None:
            raise ValueError("credentials are required when no transport is supplied")
        base: ChatClient = OpenAICompatibleClient(credentials)
    else:
        base = transport

    recorder = RecordingClient(base, run_paths=run_paths, log=log)
    limited = RateLimitedClient(
        recorder,
        rpm=settings.rate_limits.rpm,
        tpm=settings.rate_limits.tpm,
        log=log,
    )
    retrying = RetryingClient(limited, max_attempts=settings.rate_limits.max_attempts, log=log)

    if settings.cache.mode == "reuse":
        cache: Any = CachingClient.from_runs_dir(
            retrying,
            runs_dir=settings.output.runs_dir,
            log=log,
            skip=run_paths.run_dir,
        )
    else:
        cache = PassthroughClient(retrying)

    return ClientStack(client=cache, cache=cache, transport=base)
