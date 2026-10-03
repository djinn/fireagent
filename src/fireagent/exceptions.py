"""Exception hierarchy for the Fireagent SDK."""


class FireagentError(Exception):
    """Base exception for all Fireagent SDK errors."""


class InvalidRequestError(FireagentError):
    """Invalid or missing field in request (HTTP 400)."""


class UnauthorizedError(FireagentError):
    """Invalid or missing API key (HTTP 401)."""


class ForbiddenError(FireagentError):
    """Tenant or sandbox access denied (HTTP 403)."""


class NotFoundError(FireagentError):
    """Resource not found (HTTP 404)."""


class ConflictError(FireagentError):
    """Resource already exists (HTTP 409)."""


class RateLimitError(FireagentError):
    """Too many requests in a time window (HTTP 429)."""


class InternalServerError(FireagentError):
    """Unexpected server error (HTTP 500)."""


class ServiceUnavailableError(FireagentError):
    """System overloaded (HTTP 503)."""


class SandboxFailedError(FireagentError):
    """The sandbox is in a ``failed`` state and cannot execute commands."""


class SandboxTimeoutError(FireagentError):
    """The sandbox did not reach the expected state within the timeout."""


class CommandTimeoutError(FireagentError):
    """The command exceeded its execution timeout."""


class CommandOomKilledError(FireagentError):
    """The command was killed by out-of-memory."""


class NetworkDenialError(FireagentError):
    """A network policy was violated."""


# Mapping from HTTP status to exception class
STATUS_TO_EXCEPTION: dict[int, type[FireagentError]] = {
    400: InvalidRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
    500: InternalServerError,
    503: ServiceUnavailableError,
}


def map_http_status(status_code: int) -> type[FireagentError]:
    """Map an HTTP status code to the appropriate exception class."""
    return STATUS_TO_EXCEPTION.get(status_code, FireagentError)