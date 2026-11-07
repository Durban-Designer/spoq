"""Process-owned locks release on crash; a leftover filename is harmless."""
from contextlib import contextmanager
import os


@contextmanager
def migration_lock(path):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b'0')
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    except (BlockingIOError, PermissionError) as exc:
        if not acquired:
            raise ValueError('Another process is converting this project; retry after it finishes') from exc
        raise
    finally:
        # Never unlink: another waiter could otherwise lock a different inode.
        os.close(descriptor)
