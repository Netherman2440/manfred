from app.events.definitions.agent_cancelled import AgentCancelledEvent
from app.events.definitions.agent_completed import AgentCompletedEvent
from app.events.definitions.agent_failed import AgentFailedEvent
from app.events.definitions.agent_resumed import AgentResumedEvent
from app.events.definitions.agent_started import AgentStartedEvent
from app.events.definitions.agent_waiting import AgentWaitingEvent
from app.events.definitions.base import BaseEvent, EventContext, build_event_context
from app.events.definitions.generation_completed import GenerationCompletedEvent
from app.events.definitions.observation_failure import ObservationFailureEvent
from app.events.definitions.observation_started import ObservationStartedEvent
from app.events.definitions.observation_success import ObservationSuccessEvent
from app.events.definitions.reflection_started import ReflectionStartedEvent
from app.events.definitions.reflection_success import ReflectionSuccessEvent
from app.events.definitions.tool_called import ToolCalledEvent
from app.events.definitions.tool_completed import ToolCompletedEvent
from app.events.definitions.tool_failed import ToolFailedEvent
from app.events.definitions.turn_completed import TurnCompletedEvent
from app.events.definitions.turn_started import TurnStartedEvent

AgentEvent = (
    AgentCancelledEvent
    | AgentResumedEvent
    | AgentStartedEvent
    | AgentWaitingEvent
    | TurnStartedEvent
    | GenerationCompletedEvent
    | ToolCalledEvent
    | ToolCompletedEvent
    | ToolFailedEvent
    | TurnCompletedEvent
    | AgentCompletedEvent
    | AgentFailedEvent
)

ToolStreamEvent = ToolCalledEvent | ToolCompletedEvent | ToolFailedEvent

__all__ = [
    "AgentCancelledEvent",
    "AgentResumedEvent",
    "AgentCompletedEvent",
    "AgentEvent",
    "AgentFailedEvent",
    "AgentStartedEvent",
    "AgentWaitingEvent",
    "BaseEvent",
    "EventContext",
    "GenerationCompletedEvent",
    "ObservationFailureEvent",
    "ObservationStartedEvent",
    "ObservationSuccessEvent",
    "ReflectionStartedEvent",
    "ReflectionSuccessEvent",
    "ToolCalledEvent",
    "ToolCompletedEvent",
    "ToolFailedEvent",
    "ToolStreamEvent",
    "TurnCompletedEvent",
    "TurnStartedEvent",
    "build_event_context",
]
