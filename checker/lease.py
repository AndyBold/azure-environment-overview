"""A renewable-storage dependency is avoided by a hard run lifetime below 60s."""
from contextlib import contextmanager


class Busy(RuntimeError):
    pass


@contextmanager
def exclusive(blob):
    try:
        blob.upload_blob(b'overview collector lock', overwrite=False)
    except Exception as exc:
        if getattr(exc, 'status_code', None) != 409:
            raise
    try:
        lease = blob.acquire_lease(lease_duration=60)
    except Exception as exc:
        if getattr(exc, 'status_code', None) == 409:
            raise Busy('Another collector execution holds the lease') from None
        raise
    try:
        yield
    finally:
        lease.release()
