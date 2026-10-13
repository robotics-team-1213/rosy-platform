"""Mount the camera owner next to D341 pairing without importing CORE API."""
from .camera_peer_routes import configured_issuers, install_camera_peer_routes
from .camera_peer_service import CameraPeerService
from .camera_peer_store import CameraPeerStore
from .camera_peer_tls import configured_site_anchor


def install_camera_peer(app, *, pairing, current_users, require_named_operator):
    if pairing is None or not pairing.served_leaf_pem:
        return None  # Legacy constructor/protocol remains available without a v2 claim.
    anchor = configured_site_anchor(pairing.site_ca_pem, pairing.served_leaf_pem, pairing.tls_host)
    store = CameraPeerStore(pairing.store, current_issuers=lambda:configured_issuers(current_users()),
                            paired_sources=lambda:{source for source, kind in pairing.sources.items() if kind == 'paired'},
                            clock=pairing._wall, credential_lifetime_s=pairing._lifetime_s)
    service = CameraPeerService(store, identity_path=pairing.store.path.with_name(
        pairing.store.path.name + '.camera-peer.pem'), tls_anchor=anchor,
        wall=pairing._wall, monotonic=pairing._monotonic)
    install_camera_peer_routes(app, service, require_named_operator=require_named_operator,
                               current_users=current_users)
    pairing.peer_credential_allowed = store.allowed_credential
    pairing.peer_source_owned = store.source_owned
    return service
