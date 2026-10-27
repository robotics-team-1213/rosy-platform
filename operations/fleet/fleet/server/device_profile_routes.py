"""Authenticated descriptive device profiles, with no enrollment or motion routes."""

import sqlite3

from fastapi import Depends, HTTPException


def install_device_profile_routes(app, store, *, require_viewer, require_named_operator):
    def call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except sqlite3.Error:
            raise HTTPException(status_code=503, detail={"code": "DEVICE_PROFILE_STORAGE_UNAVAILABLE"}) from None

    @app.get("/api/fleet/device-profiles", tags=["fleet"])
    def list_profiles(principal=Depends(require_viewer)):
        return {"profiles": call(store.list_profiles)}

    @app.get("/api/fleet/device-profiles/{device_id}", tags=["fleet"])
    def get_profile(device_id: str, principal=Depends(require_viewer)):
        profile = call(store.get_profile, device_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "DEVICE_PROFILE_NOT_FOUND"})
        return profile

    @app.put("/api/fleet/device-profiles/{device_id}", tags=["fleet"])
    def put_profile(device_id: str, body: dict, principal=Depends(require_named_operator)):
        return call(store.put_profile, device_id, body, updated_by=principal.principal_id)
