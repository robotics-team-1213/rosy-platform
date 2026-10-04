"""Lazy CORE auth-owned identity initialization, only on a verified TLS route."""
import threading

from core_common.config import overlay_path
from .receiver_repository import OverlayRepository
from .receiver_service import PeerReceiver
from .tls_anchor import configured_tls_anchor

_initialize = threading.Lock()


def get_receiver(request):
    with _initialize:
        candidate = getattr(request.app.state, 'peer_receiver', None)
        if candidate is not None:
            return candidate
        services = request.app.state.core
        identity = services.config.get('robot', {}).get('id')
        if not isinstance(identity, str) or not identity:
            raise ValueError('provisioned receiver identity required')
        target = overlay_path()
        repository = OverlayRepository(services, target)
        configured_tls_anchor(services.config)  # Fail closed before identity initialization.
        candidate = PeerReceiver(identity, target.parent / 'peer-identity.pem', repository,
                                 anchor=lambda: configured_tls_anchor(services.config))
        request.app.state.peer_receiver = candidate
        return candidate
