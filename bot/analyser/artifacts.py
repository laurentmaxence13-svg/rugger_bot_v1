"""Publish complete local research artifacts using a same-directory replacement.

Readers see either the previous file or the completed replacement. This does not
claim directory-entry durability across a power loss or transactional publication
of several artifacts together.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile


@contextmanager
def atomic_text_writer(destination, *, newline=None):
    """Yield a UTF-8 stream and publish it only after successful write/close."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix='.' + destination.name + '.', suffix='.tmp', dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        stream = os.fdopen(descriptor, 'w', encoding='utf-8', newline=newline)
        descriptor = None  # The text stream now owns the descriptor.
        with stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def atomic_write_json(destination, value, **json_options):
    """Serialize first, then atomically publish one JSON artifact."""
    options = {'indent': 2}
    options.update(json_options)
    serialized = json.dumps(value, **options)
    with atomic_text_writer(destination) as stream:
        stream.write(serialized)
