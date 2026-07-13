"""
domain/exceptions.py

Custom error types used across the whole system. Catching one of these
specific errors tells you exactly what went wrong -- a validation
failure and a network timeout are not the same problem and should not
be handled the same way.
"""


class TicketRouterError(Exception):
    """Base class for every custom error in this project.

    Catching this one type (instead of a bare `Exception`) means code can
    catch "anything that went wrong inside ticket routing" without also
    swallowing unrelated bugs elsewhere in the program.
    """


class ValidationFailedError(TicketRouterError):
    """Raised when the AI's output still fails schema validation after
    every allowed repair attempt has been used up.
    """

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class AgentTimeoutError(TicketRouterError):
    """Raised when a single agent (e.g. the triage agent) takes longer
    than its allowed time limit to respond.
    """


class LLMProviderError(TicketRouterError):
    """Raised when the underlying AI provider (mock, Anthropic, OpenAI)
    fails in a way that isn't a validation problem -- e.g. the network
    request itself failed, or the provider returned an error.
    """


class RepositoryError(TicketRouterError):
    """Raised when saving or fetching a ticket from the database fails."""