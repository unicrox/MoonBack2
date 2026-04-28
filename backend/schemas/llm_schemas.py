from enum import StrEnum


class ModelRole(StrEnum):
    SYSTEM = "system"  # High-priority instruction context that guides model behavior.
    USER = "user"  # End-user message content.
    ASSISTANT = "assistant"  # The model's own conversational reply.
    TOOL = "tool"  # Tool execution result returned to the model.


class LangChainRole(StrEnum):
    SYSTEM = "system"
    HUMAN = "human"
    AI = "ai"
    TOOL = "tool"

    @classmethod
    def from_model_role(cls, role: ModelRole) -> "LangChainRole":
        return {
            ModelRole.SYSTEM: cls.SYSTEM,
            ModelRole.USER: cls.HUMAN,
            ModelRole.ASSISTANT: cls.AI,
        }[role]

    def to_model_role(self) -> ModelRole:
        return {
            LangChainRole.SYSTEM: ModelRole.SYSTEM,
            LangChainRole.HUMAN: ModelRole.USER,
            LangChainRole.AI: ModelRole.ASSISTANT,
            LangChainRole.TOOL: ModelRole.TOOL,
        }[self]