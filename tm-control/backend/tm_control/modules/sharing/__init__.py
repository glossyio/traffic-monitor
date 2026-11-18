"""The Sharing page: what the unit uploads, where, and what the owner agreed to (/api/v1/sharing).

The module's Module is in router.py, not here: location/config.py imports consents.py from this package, and the
router imports location/access.py, so importing the router here would make the two packages import each other.
"""
