"""Explicit, local Unix-domain client for an external isolated signing service.

No key loader or signing daemon is implemented here. An operator supplies the
absolute socket path and public key; neither environment variables nor fallback
transports are consulted. The service must implement one exchange per connection:
four-byte big-endian JSON length, UTF-8 object, response, then write-side EOF.

Request keys: version=1, nonce, public_key, message_sha256, message_b64.
Response keys: version=1, nonce, public_key, message_sha256, signature_b64.
The exact request nonce/key/digest must be echoed. Base64 must be canonical; the
64-byte signature must verify against the supplied public key and exact message.
Requests contain public transaction messages, never seeds or private material.
The daemon must independently enforce its operator's signing policy. This client
does not confer financial authority; execution admission and durable idempotence
remain mandatory independent engine checks.

Linux peer credentials and private socket permissions are required. There is no
retry, TCP transport, secret-file read, response-body logging or unbounded cleanup.
"""
import asyncio
import base64
import hashlib
import json
import math
import os
from pathlib import PurePath
import secrets
import socket
import stat
import struct

from bot.p3.certification import _decode


MAX_MESSAGE_BYTES = 1232
MAX_REQUEST_BYTES = 4096
MAX_RESPONSE_BYTES = 1024
MAX_DEADLINE_SECONDS = 2.0


class SignerError(RuntimeError):
    """Sanitized error codes only; never includes service payloads or messages."""


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_field')
        result[key] = value
    return result


def _json_constant(_):
    raise ValueError('nonfinite_json_number')


def _public_key(value):
    try:
        _decode(value)
    except (ValueError, TypeError):
        raise ValueError('explicit_signer_public_key_required') from None
    return value


class UnixDomainSigner:
    """A length-bounded, deadline-bounded external IsolatedSigner adapter.

    Socket and immediate parent must belong to the current user or the explicitly
    trusted daemon uid, with socket mode 0600 and a non-shared parent. Every
    ancestor is checked with lstat: symlinks and writable untrusted ancestors are
    refused. Root-owned sticky ancestors such as /tmp are allowed above a private
    parent. Peer uid, socket inode/device and path identity are checked again after
    connecting to limit pathname replacement attacks.
    """
    def __init__(self, socket_path, public_key, *, trusted_uid=None,
                 deadline_seconds=MAX_DEADLINE_SECONDS):
        path = os.fspath(socket_path)
        if (type(path) is not str or not path.startswith('/') or '\0' in path
                or path != os.path.normpath(path) or len(os.fsencode(path)) > 107
                or len(PurePath(path).parts) < 3):
            raise ValueError('explicit_absolute_unix_socket_path_required')
        current_uid = os.getuid()
        if trusted_uid is None:
            trusted_uid = current_uid
        if type(trusted_uid) is not int or not 0 <= trusted_uid < 2**32:
            raise ValueError('explicit_trusted_signer_uid_required')
        if (type(deadline_seconds) not in (int, float)
                or not math.isfinite(deadline_seconds)
                or not 0 < deadline_seconds <= MAX_DEADLINE_SECONDS):
            raise ValueError('signer_deadline_must_be_positive_and_at_most_two_seconds')
        if not hasattr(socket, 'SO_PEERCRED'):
            raise RuntimeError('linux_unix_peer_credentials_required')
        self._path = path
        self._public_key = _public_key(public_key)
        self._uid = trusted_uid
        self._current_uid = current_uid
        self._deadline = float(deadline_seconds)
        self._nonce_prefix = secrets.token_hex(24)
        self._sequence = 0

    @property
    def public_key(self):
        return self._public_key

    def _endpoint_identity(self):
        # lstat only: never open a private file, resolve a symlink or read a key.
        root = os.lstat('/')
        if not stat.S_ISDIR(root.st_mode) or stat.S_ISLNK(root.st_mode):
            raise ValueError('invalid_socket_root')
        administrative_uids = {0, root.st_uid}
        trusted = administrative_uids | {self._current_uid, self._uid}
        parts = PurePath(self._path).parts
        current = ''
        for index, part in enumerate(parts[1:], 1):
            current += '/' + part
            item = os.lstat(current)
            if stat.S_ISLNK(item.st_mode):
                raise ValueError('socket_symlinks_prohibited')
            if index == len(parts)-1:
                if (not stat.S_ISSOCK(item.st_mode) or stat.S_IMODE(item.st_mode) != 0o600
                        or item.st_uid != self._uid):
                    raise ValueError('private_owned_signer_socket_required')
                return item.st_dev, item.st_ino, item.st_uid, item.st_mode
            if not stat.S_ISDIR(item.st_mode) or item.st_uid not in trusted:
                raise ValueError('trusted_socket_ancestors_required')
            shared = item.st_mode & 0o022
            sticky_administrative = (item.st_mode & stat.S_ISVTX
                                     and item.st_uid in administrative_uids)
            immediate_parent = index == len(parts)-2
            if shared and (immediate_parent or not sticky_administrative):
                raise ValueError('private_socket_parent_required')
            if immediate_parent and item.st_uid not in (self._current_uid, self._uid):
                raise ValueError('private_owned_socket_parent_required')
        raise ValueError('signer_socket_missing')

    def _peer(self, writer):
        peer = writer.get_extra_info('socket')
        if peer is None or peer.family != socket.AF_UNIX:
            raise ValueError('unix_peer_socket_required')
        credentials = peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                      struct.calcsize('iII'))
        if type(credentials) is not bytes or len(credentials) != struct.calcsize('iII'):
            raise ValueError('peer_credentials_missing')
        _, uid, _ = struct.unpack('iII', credentials)
        if uid != self._uid:
            raise ValueError('signer_peer_uid_mismatch')

    @staticmethod
    def _response(payload, *, nonce, public_key, digest, message):
        response = json.loads(payload.decode('utf-8'), object_pairs_hook=_json_pairs,
                              parse_constant=_json_constant)
        if (type(response) is not dict or set(response) != {
                'version', 'nonce', 'public_key', 'message_sha256', 'signature_b64'}
                or type(response['version']) is not int or response['version'] != 1
                or response['nonce'] != nonce or response['public_key'] != public_key
                or response['message_sha256'] != digest
                or type(response['signature_b64']) is not str):
            raise ValueError('response_binding_failed')
        encoded = response['signature_b64']
        signature = base64.b64decode(encoded, validate=True)
        if (len(signature) != 64
                or base64.b64encode(signature).decode('ascii') != encoded):
            raise ValueError('canonical_signature_required')
        # Import lazily to avoid a circular import if engine consumers import this
        # adapter while loading their service configuration.
        from bot.live.engine import Ed25519Verifier
        Ed25519Verifier().verify(public_key, message, signature)
        return signature

    async def sign_message(self, message):
        if type(message) is not bytes or not 1 <= len(message) <= MAX_MESSAGE_BYTES:
            raise ValueError('bounded_exact_transaction_message_required')
        if self._sequence >= 2**64-1:
            raise SignerError('signer_nonce_sequence_exhausted')
        self._sequence += 1
        nonce = self._nonce_prefix + format(self._sequence, '016x')
        digest = hashlib.sha256(message).hexdigest()
        request = json.dumps(dict(version=1, nonce=nonce, public_key=self.public_key,
            message_sha256=digest, message_b64=base64.b64encode(message).decode('ascii')),
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(request) > MAX_REQUEST_BYTES:
            raise ValueError('bounded_signer_request_required')
        writer = None
        try:
            async with asyncio.timeout(self._deadline):
                identity = self._endpoint_identity()
                reader, writer = await asyncio.open_unix_connection(path=self._path)
                self._peer(writer)
                if self._endpoint_identity() != identity:
                    raise ValueError('signer_socket_replaced_during_connect')
                writer.write(struct.pack('>I', len(request)) + request)
                await writer.drain()
                size = struct.unpack('>I', await reader.readexactly(4))[0]
                if not 0 < size <= MAX_RESPONSE_BYTES:
                    raise ValueError('bounded_signer_response_required')
                payload = await reader.readexactly(size)
                if await reader.read(1):
                    raise ValueError('single_signer_response_required')
                return self._response(payload, nonce=nonce, public_key=self.public_key,
                                      digest=digest, message=message)
        except TimeoutError:
            raise SignerError('signer_deadline_exceeded') from None
        except Exception:
            # Service bytes, paths, transaction messages and verifier exception
            # values are never interpolated into diagnostics.
            raise SignerError('signer_exchange_refused') from None
        finally:
            if writer is not None:
                # No await wait_closed(): a malicious/broken cleanup must not
                # defeat the same absolute connect/read deadline.
                try:
                    writer.close()
                except Exception:
                    pass
