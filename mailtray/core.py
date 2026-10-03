"""Notification deduplication independent of the GUI and network."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Message:
    id: str
    sender: str
    subject: str
    url: str
    unread: bool = True


@dataclass
class SeenState:
    initialized: bool = False
    ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SeenState":
        return cls(bool(data.get("initialized")), [str(i) for i in data.get("ids", [])][:1000])

    def to_dict(self) -> dict:
        return {"initialized": self.initialized, "ids": self.ids}


def reconcile(state: SeenState, messages: list[Message]) -> list[Message]:
    known = set(state.ids)
    fresh = [message for message in reversed(messages) if message.id not in known]
    result = fresh if state.initialized else []
    state.ids = list(dict.fromkeys([*(m.id for m in messages), *state.ids]))[:1000]
    state.initialized = True
    return result
