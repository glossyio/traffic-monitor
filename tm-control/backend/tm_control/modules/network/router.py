"""GET /network: the unit's network details for any signed-in user. Nothing here holds a password."""

from fastapi import APIRouter, Depends, Request

from tm_control.core.auth import User
from tm_control.modules.auth.deps import current_user
from tm_control.modules.network.state import NetworkState, read_state
from tm_control.modules.system.router import hostname

router = APIRouter(prefix="/network", tags=["network"])


@router.get("", response_model=NetworkState)
def get_network(request: Request, user: User = Depends(current_user)) -> NetworkState:
    return read_state(request.app.state, hostname(request.app.state))
