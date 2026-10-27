# SPDX-License-Identifier: MIT OR Apache-2.0
"""Maps the shared-memory buffers a ``run`` message names.

The host creates the segments under ``/dev/shm``; the worker only opens the
ones it is given and never creates or unlinks any. A name is validated by the
protocol schema (``/cfa4-ai-`` plus 1-64 of ``A-Za-z0-9_-``), so it cannot
leave ``/dev/shm``.
"""

import mmap
import os

from .protocol import SHM_PREFIX, ProtocolError, buffer_fits

SHM_DIR = "/dev/shm"


class MappedBuffer:
    """A writable ``memoryview`` of exactly the buffer's bytes."""

    def __init__(self, buffer, writable):
        name = buffer["shm"]
        if not name.startswith(SHM_PREFIX) or "/" in name[1:]:
            raise ProtocolError("invalid", f"bad shared-memory name {name!r}", field="shm")
        path = os.path.join(SHM_DIR, name[1:])
        fd = os.open(path, (os.O_RDWR if writable else os.O_RDONLY) | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            size = os.fstat(fd).st_size
            if not buffer_fits(buffer, size):
                raise ProtocolError("invalid", f"{name}: buffer outside the {size}-byte segment", field="shm")
            access = mmap.ACCESS_WRITE if writable else mmap.ACCESS_READ
            self._map = mmap.mmap(fd, size, access=access)
        finally:
            os.close(fd)
        start = buffer["offset"]
        self._base = memoryview(self._map)
        self.view = self._base[start:start + buffer["len"]]
        self.buffer = buffer

    def close(self):
        """Unmaps the segment. If the caller still holds a slice of ``view``,
        the mapping stays alive until that slice is garbage-collected."""
        try:
            self.view.release()
            self._base.release()
            self._map.close()
        except BufferError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
