from flask import current_app

from app.identity.provider.base import IdentityProvider


def get_idv_provider() -> IdentityProvider:
    """Build the configured provider once per app. Tests may pre-set app.extensions["idv_provider"]."""
    provider = current_app.extensions.get("idv_provider")
    if provider is not None:
        return provider

    cfg = current_app.config
    if cfg["IDV_PROVIDER"] != "didit":
        raise RuntimeError("Unsupported IDV_PROVIDER")
    from app.identity.provider.didit import DiditProvider

    provider = DiditProvider(
        api_key=cfg["DIDIT_API_KEY"],
        workflow_id=cfg["DIDIT_WORKFLOW_ID"],
        base_url=cfg["DIDIT_BASE_URL"],
        sandbox_scenario=cfg["DIDIT_SANDBOX_SCENARIO"],
        connect_timeout=cfg["IDV_HTTP_CONNECT_TIMEOUT"],
        read_timeout=cfg["IDV_HTTP_READ_TIMEOUT"],
    )
    current_app.extensions["idv_provider"] = provider
    return provider
