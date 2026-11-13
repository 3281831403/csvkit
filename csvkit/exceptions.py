#!/usr/bin/env python


class CustomException(Exception):
    """
    A base exception that handles pretty-printing errors for command-line tools.
    """

    def __init__(self, msg):
        self.msg = msg

    def __unicode__(self):
        return self.msg

    def __str__(self):
        return self.msg


class ColumnIdentifierError(CustomException):
    """
    Exception raised when the user supplies an invalid column identifier.
    """
    pass


class InvalidValueForTypeException(CustomException):
    """
    Exception raised when a value can not be normalized to a specified type.
    """

    def __init__(self, index, value, normal_type):
        self.index = index
        self.value = value
        self.normal_type = normal_type
        msg = 'Unable to convert "%s" to type %s (at index %i)' % (value, normal_type, index)
        super().__init__(msg)


class RequiredHeaderError(CustomException):
    """
    Exception raised when an operation requires a CSV file to have a header row.
    """
    pass


class DuplicateColumnError(CustomException):
    """
    Exception raised when a CSV file contains column names that are not distinct,
    including names that differ only in case (which collide in case-insensitive
    databases such as SQLite).
    """
    pass


class SchemaMismatchError(CustomException):
    """
    Exception raised when multiple CSV files are loaded into the same table but
    do not share an identical column layout.
    """
    pass
