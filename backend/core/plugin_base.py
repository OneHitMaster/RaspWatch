from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI

from core.event_bus import EventBus


@dataclass(frozen=True)
class PluginContext:
    settings: dict[str, Any]
    plugins_config: dict[str, Any]
    event_bus: EventBus


class Plugin(Protocol):
    """
    Minimal plugin contract.

    Plugins are regular Python modules that expose `plugin` instance implementing:
    - `name` (string)
    - `register(app, ctx)` to add routes, ws topics, etc.
    - optional `on_sample(dynamic_payload, ctx)` to enrich the sampled metrics payload.
    """

    name: str

    def register(self, app: FastAPI, ctx: PluginContext) -> None: ...

    def on_sample(self, dynamic_payload: dict[str, Any], ctx: PluginContext) -> None: ...

