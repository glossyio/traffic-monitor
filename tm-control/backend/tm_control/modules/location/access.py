"""Reading and writing Node-RED's config.yml for the modules that edit it (Location, Cameras): load it, save it and
tell Node-RED, and turn the writer's errors into API errors. Callers hold app.state.reconcile_lock around a
load-edit-save."""

from tm_control.core.errors import ApiError
from tm_control.modules.location.config import ConfigError, NodeRedConfig


def config_error(error: ConfigError) -> ApiError:
    if error.code == "changed":
        return ApiError(409, "config_changed", "config.yml changed since it was read. Reload the page and try again.")
    return ApiError(500, "config_error", f"Node-RED's config.yml couldn't be used ({error.code}).")


def load_config(app_state) -> NodeRedConfig:
    try:
        return NodeRedConfig(app_state.config_path)
    except ConfigError as error:
        raise config_error(error) from None


def save_config(app_state, config: NodeRedConfig) -> bool:
    """Save config.yml and, when it changed, tell Node-RED (a fake one applies it; the real one watches the file)."""
    try:
        written = config.save()
    except ConfigError as error:
        raise config_error(error) from None
    if written:
        app_state.nodered.after_config_write()
    return written
