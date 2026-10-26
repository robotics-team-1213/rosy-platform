"""Installed owner stop scopes; legacy execution and recovery keep their mapping."""
from .local_stop_transport import UnixLocalStopTransport
from .physical_transfer_store import TransferInstallation


def configure_omx_stops(configured_omx, installation, stop_transport, socket_root):
    if len(set(configured_omx.values())) != len(configured_omx):
        raise ValueError("each OMX instance may be configured only once")
    targets = list(configured_omx.items())
    if installation is not None:
        installed = TransferInstallation.model_validate(installation)
        targets.extend((p.workcell_id, p.instance_id) for p in installed.policy.participants)
    targets = tuple(dict.fromkeys(targets))
    owners = {}
    for workcell_id, instance_id in targets:
        if instance_id in owners and owners[instance_id] != workcell_id:
            raise ValueError("an OMX instance cannot belong to conflicting workcells")
        owners[instance_id] = workcell_id
    if targets and stop_transport is None:
        stop_transport = UnixLocalStopTransport(socket_root)
    return targets, stop_transport
