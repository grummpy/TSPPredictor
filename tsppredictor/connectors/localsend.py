"""LocalSend: send the journal interchange file to one of your own devices on the LAN.

Implements the sender side of the LocalSend v2 HTTP protocol (prepare-upload,
then upload).  Off until you name a target device; only loopback and private
LAN addresses are accepted, never public hosts.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import uuid
from pathlib import Path

DEFAULT_PORT = 53317


def allowed_host(host: str) -> bool:
    """Loopback or private-LAN IP literals only (IPv6 brackets stripped)."""
    candidate = host.strip().strip("[]")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
    if address.is_loopback:
        return True
    if address.is_multicast or address.is_unspecified or address.is_reserved or address.is_link_local:
        return False
    if isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10"):
        return False  # carrier-grade NAT is not your LAN
    return address.is_loopback or address.is_private


def _base(host: str, port: int, https: bool) -> str:
    candidate = host.strip().strip("[]")
    literal = f"[{candidate}]" if ":" in candidate else candidate
    return f"{'https' if https else 'http'}://{literal}:{port}/api/localsend/v2"


def send_file(path: Path, host: str, *, port: int = DEFAULT_PORT, https: bool = False, session=None,
              alias: str = "TSP Predictor") -> dict:
    if not allowed_host(host):
        raise ValueError(f"LocalSend target must be a loopback or private LAN address, not {host!r}")
    import requests

    http = session or requests
    data = Path(path).read_bytes()
    file_id = uuid.uuid4().hex
    prepare = {
        "info": {"alias": alias, "version": "2.0", "deviceType": "desktop", "fingerprint": uuid.uuid4().hex,
                 "port": port, "protocol": "https" if https else "http", "download": False},
        "files": {file_id: {"id": file_id, "fileName": Path(path).name, "size": len(data),
                            "fileType": "application/json", "sha256": hashlib.sha256(data).hexdigest()}},
    }
    base = _base(host, port, https)
    response = http.post(f"{base}/prepare-upload", data=json.dumps(prepare),
                         headers={"Content-Type": "application/json"}, timeout=30, verify=False)
    response.raise_for_status()
    accepted = response.json()
    session_id = accepted["sessionId"]
    token = accepted["files"][file_id]
    upload = http.post(f"{base}/upload", params={"sessionId": session_id, "fileId": file_id, "token": token},
                       data=data, headers={"Content-Type": "application/octet-stream"}, timeout=120, verify=False)
    upload.raise_for_status()
    return {"sent": True, "host": host, "bytes": len(data), "file": Path(path).name}
