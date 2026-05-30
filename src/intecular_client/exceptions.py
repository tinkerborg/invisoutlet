"""Exceptions for the Intecular client library."""


class IntecularError(Exception):
    """Base exception for Intecular client."""


class IntecularConnectionError(IntecularError):
    """Raised when unable to connect to the device."""


class IntecularTimeoutError(IntecularError):
    """Raised when a request times out."""


class IntecularCommandError(IntecularError):
    """Raised when the device reports a command failure (PUBACK == 0)."""
