"""External signer protocol verified without sockets, private keys or a daemon.

RFC8032 section 7.1 TEST2 supplies public key/message/signature only. No secret
seed or private material is present; fake async streams emulate its response.
"""
import asyncio
import base64
import hashlib
import json
import socket
import stat
import struct
from types import SimpleNamespace

import pytest

from bot.live import signer
from bot.p3.certification import _encode


PATH = '/run/user/1000/rugger-sign.sock'
PUBLIC_KEY = _encode(bytes.fromhex(
    '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c'))
MESSAGE = bytes.fromhex('72')
SIGNATURE = bytes.fromhex(
    '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da0'
    '85ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00')


def item(kind, mode, uid, inode):
    return SimpleNamespace(st_mode=kind | mode, st_uid=uid, st_dev=1, st_ino=inode)


def filesystem():
    return {'/':item(stat.S_IFDIR, 0o755, 0, 1),
            '/run':item(stat.S_IFDIR, 0o755, 0, 2),
            '/run/user':item(stat.S_IFDIR, 0o755, 0, 3),
            '/run/user/1000':item(stat.S_IFDIR, 0o700, 1000, 4),
            PATH:item(stat.S_IFSOCK, 0o600, 1000, 5)}


class FakePeer:
    family = socket.AF_UNIX

    def __init__(self, uid=1000):
        self.uid = uid

    def getsockopt(self, level, option, length):
        assert (level, option, length) == (socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        return struct.pack('iII', 123, self.uid, 1000)


def response_for(request):
    return dict(version=1, nonce=request['nonce'], public_key=request['public_key'],
        message_sha256=request['message_sha256'],
        signature_b64=base64.b64encode(SIGNATURE).decode('ascii'))


class FakeWriter:
    def __init__(self):
        self.written = bytearray()
        self.closed = False
        self.peer = FakePeer()
        self.delay = 0

    def write(self, data):
        self.written.extend(data)

    async def drain(self):
        if self.delay:
            await asyncio.sleep(self.delay)

    def get_extra_info(self, name):
        assert name == 'socket'
        return self.peer

    def close(self):
        self.closed = True

    def request(self):
        length = struct.unpack('>I', self.written[:4])[0]
        assert length == len(self.written)-4 <= signer.MAX_REQUEST_BYTES
        return json.loads(self.written[4:])


class FakeReader:
    def __init__(self, writer, modify=None):
        self.writer = writer
        self.modify = modify or (lambda value:value)
        self.packet = None
        self.offset = 0
        self.extra = b''
        self.eof_delay = 0
        self.declared_size = None

    async def readexactly(self, count):
        if self.packet is None:
            result = self.modify(response_for(self.writer.request()))
            payload = result if type(result) is bytes else json.dumps(result).encode()
            size = len(payload) if self.declared_size is None else self.declared_size
            self.packet = struct.pack('>I', size) + payload
        result = self.packet[self.offset:self.offset+count]
        self.offset += count
        if len(result) != count:
            raise asyncio.IncompleteReadError(result, count)
        return result

    async def read(self, count):
        assert count == 1
        if self.eof_delay:
            await asyncio.sleep(self.eof_delay)
        return self.extra


def transport(monkeypatch, modify=None, *, uid=1000):
    files = filesystem()
    original_lstat = signer.os.lstat
    monkeypatch.setattr(signer.os, 'getuid', lambda:uid)

    def lstat(path, *args, **kwargs):
        path = str(path)
        return files[path] if path in files else original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(signer.os, 'lstat', lstat)
    writer = FakeWriter()
    reader = FakeReader(writer, modify)
    calls = []

    async def connect(*, path):
        calls.append(path)
        return reader, writer

    monkeypatch.setattr(signer.asyncio, 'open_unix_connection', connect)
    return signer.UnixDomainSigner(PATH, PUBLIC_KEY), files, reader, writer, calls


def run(client, message=MESSAGE):
    return asyncio.run(client.sign_message(message))


def test_rfc8032_public_signature_verifies_exact_message_through_external_protocol(monkeypatch):
    client, _, _, writer, calls = transport(monkeypatch)
    assert run(client) == SIGNATURE
    assert client.public_key == PUBLIC_KEY and writer.closed and calls == [PATH]
    request = writer.request()
    assert set(request) == {'version','nonce','public_key','message_sha256','message_b64'}
    assert request['version'] == 1 and type(request['version']) is int
    assert request['public_key'] == PUBLIC_KEY
    assert request['message_b64'] == base64.b64encode(MESSAGE).decode('ascii')
    assert request['message_sha256'] == hashlib.sha256(MESSAGE).hexdigest()
    assert len(request['nonce']) == 64


@pytest.mark.parametrize('path', [
    'rugger.sock', 'unix:///run/user/1000/socket', 'tcp://localhost:123',
    '/run/user/1000/../1000/socket', '/run//user/1000/socket', '/run/user/1000/socket/',
    '/run/user/1000/socket\0x', '/s', '/'+'a'*108,
])
def test_only_explicit_canonical_absolute_unix_paths(path):
    with pytest.raises(ValueError):
        signer.UnixDomainSigner(path, PUBLIC_KEY)


@pytest.mark.parametrize('deadline', [0,-1,2.0001,True,float('inf'),float('nan'),'2'])
def test_deadline_never_exceeds_two_seconds_or_uses_truthy_coercion(deadline):
    with pytest.raises(ValueError):
        signer.UnixDomainSigner(PATH, PUBLIC_KEY, deadline_seconds=deadline)


@pytest.mark.parametrize('uid', [True,-1,2**32,'1000'])
def test_trusted_uid_is_explicit_native_bounded_integer(uid):
    with pytest.raises(ValueError):
        signer.UnixDomainSigner(PATH, PUBLIC_KEY, trusted_uid=uid)


@pytest.mark.parametrize('public_key', ['',None,'wallet-name','1'*31])
def test_signer_identity_requires_actual_public_key(public_key):
    with pytest.raises(ValueError):
        signer.UnixDomainSigner(PATH, public_key)


@pytest.mark.parametrize('message', [b'',b'a'*1233,'72',bytearray(b'r'),None])
def test_message_is_exact_bounded_bytes_before_any_connection(monkeypatch, message):
    client, _, _, _, calls = transport(monkeypatch)
    with pytest.raises(ValueError):
        run(client, message)
    assert calls == []


@pytest.mark.parametrize('path,replacement', [
    (PATH,item(stat.S_IFREG,0o600,1000,5)),
    (PATH,item(stat.S_IFSOCK,0o660,1000,5)),
    (PATH,item(stat.S_IFSOCK,0o600,1001,5)),
    (PATH,item(stat.S_IFLNK,0o777,1000,5)),
    ('/run/user/1000',item(stat.S_IFLNK,0o700,1000,4)),
    ('/run/user/1000',item(stat.S_IFDIR,0o770,1000,4)),
    ('/run/user/1000',item(stat.S_IFDIR,0o755,0,4)),
    ('/run/user',item(stat.S_IFDIR,0o755,1001,3)),
    ('/run',item(stat.S_IFDIR,0o777,0,2)),
])
def test_insecure_socket_or_ancestor_is_rejected_before_connect(monkeypatch, path, replacement):
    client, files, _, _, calls = transport(monkeypatch)
    files[path] = replacement
    with pytest.raises(signer.SignerError, match='signer_exchange_refused'):
        run(client)
    assert calls == []


def test_explicit_trusted_daemon_uid_requires_matching_socket_and_peer(monkeypatch):
    _, files, reader, writer, calls = transport(monkeypatch)
    files[PATH] = item(stat.S_IFSOCK,0o600,2000,5)
    files['/run/user/1000'] = item(stat.S_IFDIR,0o700,2000,4)
    writer.peer.uid = 2000
    client = signer.UnixDomainSigner(PATH, PUBLIC_KEY, trusted_uid=2000)
    assert run(client) == SIGNATURE and calls == [PATH]


@pytest.mark.parametrize('peer', [None, FakePeer(1001), SimpleNamespace(family=socket.AF_INET)])
def test_peer_uid_and_unix_family_are_verified_before_request(monkeypatch, peer):
    client, _, _, writer, calls = transport(monkeypatch)
    writer.peer = peer
    with pytest.raises(signer.SignerError):
        run(client)
    assert calls == [PATH] and writer.closed and writer.written == b''


def test_socket_replacement_during_connect_is_rejected(monkeypatch):
    client, files, reader, writer, calls = transport(monkeypatch)

    async def replaced(*, path):
        calls.append(path)
        files[PATH] = item(stat.S_IFSOCK,0o600,1000,99)
        return reader, writer

    monkeypatch.setattr(signer.asyncio, 'open_unix_connection', replaced)
    with pytest.raises(signer.SignerError):
        run(client)
    assert writer.closed and writer.written == b'' and calls == [PATH]


@pytest.mark.parametrize('changes', [
    {'version':True}, {'version':2}, {'nonce':'old-replayed-nonce'},
    {'public_key':_encode(bytes([23])*32)}, {'message_sha256':'0'*64},
    {'unexpected_secret_field':'not-accepted'}, {'signature_b64':None},
    {'signature_b64':base64.b64encode(bytes(63)).decode()},
    {'signature_b64':base64.b64encode(bytes(65)).decode()},
    {'signature_b64':base64.b64encode(bytes(64)).decode()},
    {'signature_b64':base64.b64encode(SIGNATURE).decode()+'\n'},
])
def test_response_schema_binding_and_actual_signature_are_all_mandatory(monkeypatch, changes):
    client, _, _, writer, calls = transport(monkeypatch,
        lambda value:dict(value, **changes))
    with pytest.raises(signer.SignerError, match='signer_exchange_refused') as error:
        run(client)
    assert writer.closed and calls == [PATH]
    assert str(error.value) == 'signer_exchange_refused'


@pytest.mark.parametrize('payload', [
    b'{}', b'[]', b'null', b'{"version":1,"version":1}', b'{"x":NaN}',
    b'{"x":Infinity}', b'{invalid json', b'\xff', b'{}{}',
])
def test_invalid_or_duplicate_json_is_rejected_without_raw_error_payload(monkeypatch, payload):
    client, _, _, writer, _ = transport(monkeypatch, lambda _:payload)
    with pytest.raises(signer.SignerError) as error:
        run(client)
    assert str(error.value) == 'signer_exchange_refused' and writer.closed


def test_same_public_signature_cannot_verify_a_tampered_message(monkeypatch):
    client, _, _, writer, _ = transport(monkeypatch)
    with pytest.raises(signer.SignerError):
        run(client, b's')
    assert writer.closed


def test_noncanonical_base64_padding_bits_are_rejected(monkeypatch):
    def changed(value):
        encoded = value['signature_b64']
        # Last signature byte is 0; 'A' and 'B' both decode under permissive
        # padding-bit rules, but only 'A' is the canonical representation.
        value['signature_b64'] = encoded[:-3] + 'B=='
        assert base64.b64decode(value['signature_b64'], validate=True) == SIGNATURE
        return value

    client, _, _, writer, _ = transport(monkeypatch, changed)
    with pytest.raises(signer.SignerError):
        run(client)
    assert writer.closed


@pytest.mark.parametrize('declared', [0,1025,2**32-1,1000])
def test_frame_length_and_truncation_are_bounded(monkeypatch, declared):
    client, _, reader, writer, calls = transport(monkeypatch)
    reader.declared_size = declared
    with pytest.raises(signer.SignerError):
        run(client)
    assert writer.closed and calls == [PATH]


def test_extra_frame_bytes_are_not_silently_accepted(monkeypatch):
    client, _, reader, writer, _ = transport(monkeypatch)
    reader.extra = b'X'
    with pytest.raises(signer.SignerError):
        run(client)
    assert writer.closed


@pytest.mark.parametrize('phase', ['connect','write','eof'])
def test_single_absolute_deadline_covers_connect_write_read_and_cleanup(monkeypatch, phase):
    _, _, reader, writer, calls = transport(monkeypatch)
    client = signer.UnixDomainSigner(PATH, PUBLIC_KEY, deadline_seconds=0.01)
    if phase == 'connect':
        async def blocked(*, path):
            calls.append(path)
            await asyncio.sleep(1)
            return reader, writer
        monkeypatch.setattr(signer.asyncio, 'open_unix_connection', blocked)
    elif phase == 'write':
        writer.delay = 1
    else:
        reader.eof_delay = 1
    with pytest.raises(signer.SignerError, match='signer_deadline_exceeded'):
        run(client)
    assert calls == [PATH]
    if phase != 'connect':
        assert writer.closed


def test_connection_exception_is_sanitized_and_not_retried(monkeypatch):
    client, _, _, _, calls = transport(monkeypatch)

    async def refused(*, path):
        calls.append(path)
        raise OSError('DO-NOT-EXPOSE-service-payload-or-private-path')

    monkeypatch.setattr(signer.asyncio, 'open_unix_connection', refused)
    with pytest.raises(signer.SignerError) as error:
        run(client)
    assert calls == [PATH] and str(error.value) == 'signer_exchange_refused'


def test_a_previous_response_cannot_be_replayed_for_new_nonce(monkeypatch):
    client, _, _, writer, _ = transport(monkeypatch)
    assert run(client) == SIGNATURE
    old_response = response_for(writer.request())
    next_writer = FakeWriter()
    next_reader = FakeReader(next_writer, lambda _:old_response)

    async def next_connection(*, path):
        return next_reader, next_writer

    monkeypatch.setattr(signer.asyncio, 'open_unix_connection', next_connection)
    with pytest.raises(signer.SignerError):
        run(client)
    assert next_writer.request()['nonce'] != old_response['nonce']
    assert next_writer.closed


def test_cancellation_closes_connection_and_propagates(monkeypatch):
    client, _, reader, writer, _ = transport(monkeypatch)
    writer.delay = 1

    async def cancelled():
        task = asyncio.create_task(client.sign_message(MESSAGE))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancelled())
    assert writer.closed
