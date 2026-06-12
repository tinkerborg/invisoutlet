"""Exceptions for the InvisOutlet client library."""


class InvisOutletError(Exception):
    """Base exception for InvisOutlet client."""


class InvisOutletConnectionError(InvisOutletError):
    """Raised when unable to connect to the device."""


class InvisOutletTimeoutError(InvisOutletError):
    """Raised when a request times out."""


class InvisOutletCommandError(InvisOutletError):
    """Raised when the device reports a command failure (PUBACK == 0)."""
