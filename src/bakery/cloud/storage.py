"""The till export, when it lives in Amazon S3.

A real till writes its export somewhere the agent can reach, and on AWS that is
an S3 bucket. Everything downstream reads a local file, and the corrected
history cache is keyed on that file's modification time. So this module does one
job: when the bills path is an s3:// URI, keep a local copy current and return
its path.

The local copy is stamped with the object's LastModified time. A new export in
the bucket therefore changes the local mtime, which invalidates the cache and
rebuilds the history, exactly as a new local file would.

Dormant until BILLS_FILE starts with s3://. boto3 is imported only then.
"""

import os
import time

# How often to ask S3 whether the export changed. Pages call into the shop many
# times a minute; one HEAD request per call would add a network round trip to
# every page load for no benefit.
CHECK_EVERY_SECONDS = 60

_last_checked = {}


def is_s3(path):
    return isinstance(path, str) and path.startswith("s3://")


def split(uri):
    """s3://bucket/key/parts -> ("bucket", "key/parts")."""
    rest = uri[len("s3://"):]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(f"{uri!r} is not a full s3://bucket/key path.")
    return bucket, key


def local_copy(uri, cache_dir, client=None, now=None):
    """Download the export if it changed, and return the local path."""
    bucket, key = split(uri)
    target = os.path.join(cache_dir, os.path.basename(key))
    now = time.monotonic() if now is None else now

    recent = _last_checked.get(uri)
    if recent is not None and now - recent < CHECK_EVERY_SECONDS \
            and os.path.exists(target):
        return target

    if client is None:
        import boto3
        client = boto3.client("s3")

    head = client.head_object(Bucket=bucket, Key=key)
    remote = head["LastModified"].timestamp()

    if not (os.path.exists(target) and abs(os.path.getmtime(target) - remote) < 1):
        os.makedirs(cache_dir, exist_ok=True)
        partial = target + ".part"
        client.download_file(bucket, key, partial)
        os.replace(partial, target)          # a reader never sees half a file
        os.utime(target, (remote, remote))

    _last_checked[uri] = now
    return target
