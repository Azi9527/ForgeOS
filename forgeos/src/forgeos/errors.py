"""ForgeOS domain and persistence errors."""


class ForgeError(RuntimeError):
    """Base error for failures with stable ForgeOS semantics."""


class ForgeConfigError(ForgeError):
    """Raised when Forge configuration is invalid or incompatible."""


class ForgeConflictError(ForgeError):
    """Raised when persisted state changed since the caller read it."""


class ForgeNotFoundError(ForgeError):
    """Raised when a requested Forge object does not exist."""


class ForgeRuntimeUnavailableError(ForgeError):
    """Raised when a required local runtime executable is unavailable."""


class InvalidTransitionError(ForgeError):
    """Raised when a ForgeTask state transition violates the state machine."""


class ForgeValidationError(ForgeError):
    """Raised when validation cannot execute according to its declared contract."""


class ForgePolicyError(ForgeError):
    """Raised when a fail-closed ForgePolicy gate denies an operation."""


class ForgeBudgetError(ForgeError):
    """Raised when an execution or repair budget is exhausted."""


class ForgeIntegrityError(ForgeError):
    """Raised when persisted Forge evidence fails an integrity gate."""


class ForgeBundleError(ForgeError):
    """Raised when a Forge export bundle is unsafe, corrupt, or incompatible."""


class ForgeReleaseError(ForgeError):
    """Raised when a release-readiness contract cannot be evaluated safely."""
