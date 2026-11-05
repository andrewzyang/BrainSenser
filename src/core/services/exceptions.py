"""
Custom exceptions for the service layer.

These exceptions provide specific error handling for service-level operations,
allowing consumers to handle different error scenarios appropriately.
"""


class ServiceError(Exception):
    """Base exception for all service-level errors."""


class PatientNotFoundError(ServiceError):
    """Raised when a requested patient does not exist."""


class PatientAlreadyExistsError(ServiceError):
    """Raised when attempting to create a patient that already exists."""


class InvalidPatientIDError(ServiceError):
    """Raised when a patient ID is invalid or malformed."""


class DatabaseInitializationError(ServiceError):
    """Raised when patient database initialization fails."""


class DataNotFoundError(ServiceError):
    """Raised when requested data does not exist."""

    def __init__(self, message: str, user_message: str = None):
        super().__init__(message)
        self.user_message = user_message or message
