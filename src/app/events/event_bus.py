from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable

from app.events.definitions import BaseEvent

EventHandler = Callable[[BaseEvent], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)

    def emit(self, event: BaseEvent) -> None:
        specific_handlers = tuple(self._handlers.get(getattr(event, "type"), ()))
        any_handlers = tuple(self._handlers.get("any", ()))

        for handler in specific_handlers:
            self._safe_call(handler, event)

        for handler in any_handlers:
            self._safe_call(handler, event)

    def subscribe(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        self._handlers[event_type].append(handler)

        def unsubscribe() -> None:
            handlers = self._handlers.get(event_type)
            if not handlers:
                return
            try:
                handlers.remove(handler)
            except ValueError:
                return
            if not handlers:
                self._handlers.pop(event_type, None)

        return unsubscribe

    def _safe_call(self, handler: EventHandler, event: BaseEvent) -> None:
        try:
            handler(event)
        except Exception:
            self._logger.exception("Event handler failed for %s", getattr(event, "type", "unknown"))
