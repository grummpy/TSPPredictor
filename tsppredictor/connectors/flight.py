"""Arrow Flight: serve price frames to a notebook on your own network (optional ``pyarrow``).

Read-only. Binds to loopback by default; a LAN address must be a private or
loopback IP (same rule as the LocalSend connector) and needs ``allow_lan=True``.
"""

from __future__ import annotations

import pandas as pd

from tsppredictor.connectors.localsend import allowed_host


def available() -> bool:
    try:
        import pyarrow.flight  # noqa: F401
    except ImportError:
        return False
    return True


def check_bind(host: str, allow_lan: bool = False) -> str:
    bare = host.strip("[]")
    if bare in ("127.0.0.1", "::1", "localhost"):
        return bare
    if not allowed_host(bare):
        raise ValueError(f"Flight may only bind to loopback or a private LAN address, not {host!r}")
    if not allow_lan:
        raise ValueError("binding beyond loopback needs allow_lan=True (tsp flight --allow-lan)")
    return bare


def make_server(frames: dict[str, pd.DataFrame], host: str = "127.0.0.1", port: int = 8815, *, allow_lan: bool = False):
    if not available():
        raise RuntimeError("Arrow Flight needs pyarrow (pip install pyarrow)")
    import pyarrow as pa
    import pyarrow.flight as fl

    bind = check_bind(host, allow_lan)
    tables = {name: pa.Table.from_pandas(frame.reset_index()) for name, frame in frames.items()}

    class PriceServer(fl.FlightServerBase):
        def list_flights(self, context, criteria):
            for name, table in tables.items():
                yield fl.FlightInfo(table.schema, fl.FlightDescriptor.for_path(name), [], table.num_rows, -1)

        def do_get(self, context, ticket):
            name = ticket.ticket.decode()
            if name not in tables:
                raise fl.FlightServerError(f"unknown frame {name}")
            return fl.RecordBatchStream(tables[name])

        def do_put(self, context, descriptor, reader, writer):
            raise fl.FlightServerError("read-only server")

    location = f"grpc://{'[' + bind + ']' if ':' in bind else bind}:{port}"
    return PriceServer(location), location


def fetch(location: str, name: str) -> pd.DataFrame:
    """Client side, for the notebook: pull one frame by name."""
    import pyarrow.flight as fl

    client = fl.connect(location)
    return client.do_get(fl.Ticket(name.encode())).read_all().to_pandas()
