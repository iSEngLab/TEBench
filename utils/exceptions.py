"""
TUBench Exception Definitions Module

Defines the exception hierarchy used in the project, distinguishing between recoverable and unrecoverable errors.
"""


class TUBenchException(Exception):
    """TUBench base exception class"""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ============ Recoverable Exceptions ============
# When these exceptions occur, the current item can be skipped and processing continues

class RecoverableError(TUBenchException):
    """Recoverable error - skip the current item and continue processing"""
    pass


class ParseError(RecoverableError):
    """Parse error - failed to parse Java code, Diff, XML, etc."""
    pass


class GitOperationError(RecoverableError):
    """Git operation error - checkout, diff, apply, etc. failed"""
    pass


class CompilationError(RecoverableError):
    """Compilation error - Maven compilation failed"""
    pass


class CoverageError(RecoverableError):
    """Coverage analysis error - failed to parse JaCoCo report"""
    pass


# ============ Fatal Exceptions ============
# When these exceptions occur, the entire execution should be terminated

class FatalError(TUBenchException):
    """Fatal error - terminates execution"""
    pass


class ConfigurationError(FatalError):
    """Configuration error - cannot continue running"""
    pass


class RepositoryError(FatalError):
    """Repository error - repository does not exist or is corrupted"""
    pass
