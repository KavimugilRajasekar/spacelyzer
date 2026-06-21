import sys

class SpacelyzerException(Exception):
    """Base exception for Spacelyzer with associated exit code."""
    exit_code = 1

class PermissionDeniedException(SpacelyzerException):
    exit_code = 2

class PathNotFoundException(SpacelyzerException):
    exit_code = 3

class UserCancelledException(SpacelyzerException):
    exit_code = 4
