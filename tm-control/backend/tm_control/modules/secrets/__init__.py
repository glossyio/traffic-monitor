"""The entered secrets (the ThingsBoard access token, and the Plate Recognizer token and license key when the add-on
is installed): whether each is set, and setting or removing one through the set-secret root job. Admins only."""

from tm_control.modules import Module
from tm_control.modules.secrets.router import router

module = Module("secrets", router)
