"""What a route answers when the disk under the pictures fails.

An OSError from the store carries the path of the file it failed on, which ends in a picture's id. A route turns it into
one of these answers, with a fixed message, and raises it `from None`, so neither the path nor the id reaches the
response, the error log, or a traceback.
"""

import errno

from tm_control.core.errors import ApiError


def storage_error(error: OSError, keeping: bool = False) -> ApiError:
    """The answer for a failed disk: 409 no_space when a keep ran out of room, else 500 storage."""
    if keeping and error.errno == errno.ENOSPC:
        return ApiError(409, "no_space", "There isn't enough free space on the device to keep these pictures.")
    return ApiError(
        500, "storage",
        "The device couldn't read or write its stored pictures. Try again, and check the device's storage if it keeps "
        "happening.",
    )
