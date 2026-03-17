from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from core.event_bus import EventBus
from core.plugin_base import Plugin, PluginContext


@dataclass
class LoadedPlugin:
    name: str
    plugin: Plugin


class PluginManager:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._loaded: list[LoadedPlugin] = []

    @property
    def loaded_names(self) -> list[str]:
        return [p.name for p in self._loaded]

    def load_from_settings(self, app: FastAPI, settings: dict[str, Any]) -> None:
        enabled = settings.get("plugins_enabled") or []
        if not isinstance(enabled, list):
            enabled = []
        plugins_config = settings.get("plugins_config") or {}
        if not isinstance(plugins_config, dict):
            plugins_config = {}

        ctx = PluginContext(settings=settings, plugins_config=plugins_config, event_bus=self._event_bus)

        for name in enabled:
            if not isinstance(name, str) or not name.strip():
                continue
            try:
                mod = importlib.import_module(f"plugins.{name}")
                plug = getattr(mod, "plugin", None)
                if plug is None:
                    continue
                plug_name = getattr(plug, "name", name)
                try:
                    plug.register(app, ctx)
                except Exception:
                    continue
                self._loaded.append(LoadedPlugin(name=str(plug_name), plugin=plug))
            except Exception:
                continue

    def on_sample(self, dynamic_payload: dict[str, Any], settings: dict[str, Any]) -> None:
        plugins_config = settings.get("plugins_config") or {}
        if not isinstance(plugins_config, dict):
            plugins_config = {}
        ctx = PluginContext(settings=settings, plugins_config=plugins_config, event_bus=self._event_bus)
        for p in list(self._loaded):
            hook = getattr(p.plugin, "on_sample", None)
            if callable(hook):
                try:
                    hook(dynamic_payload, ctx)
                except Exception:
                    pass

