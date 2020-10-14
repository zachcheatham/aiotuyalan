import logging
import asyncio
import socket
import time
import json
import base64
import bitstring
import binascii
import traceback
import pyaes

from typing import Optional, Tuple, List, Any
from hashlib import md5

_LOGGER = logging.getLogger(__name__)

PING_TIME = 10

COMMAND_UDP = 0
COMMAND_AP_CONFIG = 1
COMMAND_ACTIVE = 2
COMMAND_BIND = 3
COMMAND_RENAME_GW = 4
COMMAND_RENAME_DEVICE = 5
COMMAND_UNBIND = 6
COMMAND_CONTROL = 7
COMMAND_HEART_BEAT = 9
COMMAND_STATUS = 8
COMMAND_DP_QUERY = 10
COMMAND_QUERY_WIFI = 11
COMMAND_TOKEN_BIND = 12
COMMAND_CONTROL_NEW = 13
COMMAND_ENABLE_WIFI = 14
COMMAND_DP_QUERY_NEW = 16
COMMAND_SCENE_EXECUTE = 17
COMMAND_UDP_NEW = 19
COMMAND_AP_CONFIG_NEW = 20
COMMAND_LAN_GW_ACTIVE = 240
COMMAND_LAN_SUB_DEV_REQUEST = 241
COMMAND_LAN_DELETE_SUB_DEV = 242
COMMAND_LAN_REPORT_SUB_DEV = 243
COMMAND_LAN_SCENE = 244
COMMAND_LAN_PUBLISH_CLOUD_CONFIG = 245
COMMAND_LAN_PUBLISH_APP_CONFIG = 246
COMMAND_LAN_EXPORT_APP_CONFIG = 247
COMMAND_LAN_PUBLISH_SCENE_PANEL = 248
COMMAND_LAN_REMOVE_GW = 249
COMMAND_LAN_CHECK_GW_UPDATE = 250
COMMAND_LAN_GW_UPDATE = 251
COMMAND_LAN_SET_GW_CHANNEL = 252

PACKET_PREFIX = b'\x00\x00\x55\xaa'
PACKET_SUFFIX = b'\x00\x00\xaa\x55'

# Thanks https://stackoverflow.com/questions/45419723/python-timer-with-asyncio-coroutine
class Timer:
    def __init__(self, timeout, callback):
        self._timeout = timeout
        self._callback = callback
        self._task = asyncio.ensure_future(self._job())

    async def _job(self):
        await asyncio.sleep(self._timeout)
        await self._callback()

    def cancel(self):
        self._task.cancel()

class TuyaCipher:
    def __init__(self, key, version, bs=16):
        self._key = key.encode('latin1')
        self._version = version
        self._bs = bs


    async def encrypt(self, data, b64=True) -> bytes:
        #data = self._pad(data)
        #cipher = AES.new(self._key, AES.MODE_ECB)
        #encrypted_data = cipher.encrypt(data)

        cipher = pyaes.blockfeeder.Encrypter(pyaes.AESModeOfOperationECB(self._key))
        encrypted_data = cipher.feed(data)
        encrypted_data += cipher.feed()

        if b64:
            return base64.b64encode(encrypted_data)
        else:
            return encrypted_data


    async def decrypt(self, data, b64=True) -> bytes:

        if b64:
            data = base64.b64decode(data)
            _LOGGER.debug("DECRYPT B64: %s", data.hex())

        cipher = pyaes.blockfeeder.Decrypter(pyaes.AESModeOfOperationECB(self._key))
        raw = cipher.feed(data)
        raw += cipher.feed()
        return raw

        #data = self._pad(data)
        #log.debug("DECRYPT PAD: %s", data.hex())

        #cipher = AES.new(self._key, AES.MODE_ECB)
        #raw = cipher.decrypt(data)
        #raw = self._unpad(raw)

        return raw

    def _pad(self, data) -> bytes:
        length = 16 - (len(data) % 16)
        data += bytes([length])*length
        return data

    @staticmethod
    def _unpad(data):
        return data[:-ord(data[len(data)-1:])]



class TuyaClient:
    def __init__(self, device_info, key, event_loop, on_stop, on_payload):
        self._device_info = device_info
        self._event_loop = event_loop
        self._on_stop = on_stop
        self._on_payload = on_payload
        self._stopped = False
        self._socket = None
        self._socket_reader = None
        self._socket_writer = None
        self._write_lock = asyncio.Lock()
        self._seq_lock = asyncio.Lock()
        self._authenticated = False
        self._socket_connected = False
        self._sequenceN = 0
        self._key = key
        self._cipher = TuyaCipher(key, device_info['version'])


    async def send(self, command, dps, encrypted=False) -> None:
        if not self._socket_connected:
            raise Exception("Not connected to device.")

        payload = {
            "gwId": self._device_info["gw_id"],
            "devId": self._device_info["id"],
            "t": int(time.time()),
            "dps": dps,
            "uid": self._device_info["id"]
        }

        msg = await self._encode(payload, command, encrypted=encrypted)

        await self._write(msg)


    async def connect(self) -> None:
        if self._stopped:
            raise Exception("Connection is closed.")
        if self._socket_connected:
            raise Exception("Already connected.")

        try:
            _LOGGER.debug("Resolving ip address...")
            coro = self.resolve_ip_address()
            sockaddr = await asyncio.wait_for(coro, 30.0)
        except asyncio.TimeoutError as err:
            await self._on_error()
            raise Exception("Timeout while resolving IP address.")
        except Exception as err:
            await self._on_error()
            raise err

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setblocking(False)
        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        _LOGGER.info("Connecting to Tuya device: %r", sockaddr)

        try:
            coro = self._event_loop.sock_connect(self._socket, sockaddr)
            await asyncio.wait_for(coro, 30.0)
        except OSError as err:
            await self._on_error()
            raise Exception("Error connecting to {}: {}".format(sockaddr, err))
        except asyncio.TimeoutError:
            await self._on_error()
            raise Exception("Timeout while connecting to {}".format(sockaddr))

        _LOGGER.debug("Socket opened for {}".format(sockaddr))

        self._socket_reader, self._socket_writer = await asyncio.open_connection(sock=self._socket)
        self._socket_connected = True
        self._event_loop.create_task(self._run_loop())
        self._event_loop.create_task(self._ping_loop())


    async def _ping_loop(self) -> None:
        try:
            while self._socket_connected:
                await asyncio.sleep(PING_TIME)
                if self._socket_connected:
                    msg = await self._encode(None, COMMAND_HEART_BEAT)
                    await self._write(msg)
        except Exception as err:
            _LOGGER.error("Unable to send ping to %s: %s", self._device_info['address'], err)
            traceback.print_exc()


    async def _run_loop(self) -> None:
        next_msg_timeout = None
        msg_lock = asyncio.Lock()
        raw_messages = []

        async def _on_nxt_msg_timeout():
            nonlocal msg_lock
            nonlocal raw_messages
            nonlocal self

            raw_messages_cpy = None
            async with msg_lock:
                raw_messages_cpy = raw_messages.copy()
                raw_messages.clear()

            await self._parse_messages(raw_messages_cpy)

        while self._socket_connected:
            try:
                message = await self._recv()
                async with msg_lock:
                    if next_msg_timeout is not None:
                        next_msg_timeout.cancel()

                    raw_messages.append(message)
                    next_msg_timeout = Timer(0.1, _on_nxt_msg_timeout)
                    #_LOGGER.debug("Received raw message: %s", message.hex())

            except Exception as err:
                _LOGGER.info("Error while reading incoming message from %s: %s", self._device_info["address"], err)
                await self._on_error()
                break


    async def _parse_messages(self, messages) -> None:
        _LOGGER.debug("Processing %d message(s) from device.", len(messages))
        parsed_messages = []
        for raw_message in messages:
            try:
                command, payload = await self._decode(raw_message)
                parsed_messages.append((command, payload))
            except Exception as err:
                _LOGGER.error("An error occured while parsing a message: %s", err)
                traceback.print_exc()

        for command, payload in parsed_messages:
            try:
                if command == COMMAND_HEART_BEAT:
                    _LOGGER.debug("Received pong from %s", self._device_info['address'])
                else:
                    await self._on_payload(command, payload)
            except Exception as err:
                _LOGGER.error("An error occured while handling a payload: %s", err)
                traceback.print_exc()


    async def _recv(self) -> bytes:
        try:
            while True: # Find packet prefix to start packet, if not, we're throwing out bytes until we find it...
                ret = await self._socket_reader.read(4)
                if ret != PACKET_PREFIX:
                    _LOGGER.warning("Expected packet prefix (%s) received: %s", PACKET_PREFIX.hex(), ret.hex())
                else:
                    message = ret
                    break

            header = await self._socket_reader.read(8)
            payload_length_bytes = await self._socket_reader.read(4)
            payload_length = int.from_bytes(payload_length_bytes, "big")
            rest_of_msg = await self._socket_reader.read(payload_length)

            return PACKET_PREFIX + header + payload_length_bytes + rest_of_msg

        except (OSError, TimeoutError) as err:
            raise Exception("Error while receiving data: {}".format(err))

        return None


    async def _write(self, data: bytes) -> None:
        if not self._socket_connected:
            raise Exception("Socket is not connected.")

        #_LOGGER.debug("Wrote: %s", data.hex())

        try:
            async with self._write_lock:
                self._socket_writer.write(data)
                await self._socket_writer.drain()
        except OSError as err:
            await self._on_error()
            raise Exception("Error while writing data: {}".format(err))


    async def stop(self) -> None:
        if self._stopped:
            return

        self._stopped = True

        await self._close_socket()
        await self._on_stop()


    async def _on_error(self) -> None:
        await self.stop()

    async def _close_socket(self) -> None:
        if not self._socket_connected:
            return
        async with self._write_lock:
            self._socket_writer.close()
            self._socket_writer = None
            self._socket_reader = None
        if self._socket is not None:
            self._socket.close()
        self._socket_connected = False
        self._connected = False
        _LOGGER.info("Closed socket to TuyaDeivce at %s:%d", self._device_info["address"], self._device_info["port"])


    async def resolve_ip_address(self) -> Tuple[Any, ...]:
        try:
            res = await self._event_loop.getaddrinfo(self._device_info["address"], self._device_info["port"], family=socket.AF_INET, proto=socket.IPPROTO_TCP)
        except OSError as err:
            raise Exception("Error resolving IP address: {}".format(err))

        if not res:
            raise Exception("Error resolving IP address: No matches!")

        _, _, _, _, sockaddr = res[0]

        return sockaddr


    async def _encode(self, payload, typeByte, encrypted=False) -> bytes:

        _LOGGER.debug("Sending Command: %d. Payload %r", typeByte, payload)

        json_payload = None
        if payload is not None:
            _LOGGER.debug(payload)
            json_payload = json.dumps(payload, separators=(',', ':'))
            json_payload = json_payload.encode('utf-8')
        else:
            json_payload = b''

        if self._device_info['version'] == '3.3':
            json_payload = await self._cipher.encrypt(json_payload, b64=False)

            if typeByte != COMMAND_DP_QUERY:
                json_payload = "3.3".encode('utf-8') + b"\0\0\0\0\0\0\0\0\0\0\0\0" + json_payload
                #_LOGGER.debug("Adding 3.3 non query header: %s", json_payload)

            #_LOGGER.debug("V3.3 Encrypted payload: %s", json_payload.hex())
        elif encrypted:
            json_payload = await self._cipher.encrypt(json_payload, b64=True)

            #_LOGGER.debug("V3.1 Encrypted payload: %s", json_payload.hex())

            md5_signature = b'data=' + json_payload + b'||lpv=' + self._device_info['version'].encode('ascii', errors='strict') + b'||' + self._key.encode('latin1', errors='strict')

            m = md5()
            m.update(md5_signature)
            md5_signature = m.digest()
            #_LOGGER.debug("Hex Signature: " + md5_signature.hex())

            json_payload = self._device_info['version'].encode('ascii', errors='strict') + md5_signature + json_payload

            #_LOGGER.debug("V3.1 Full Encrypted Payload: %s", json_payload.hex())

        sequenceN = None
        async with self._seq_lock:
            sequenceN = self._sequenceN
            self._sequenceN += 1

        stream = bitstring.BitStream()
        stream.append("uint:32=21930")
        stream.append("uint:32=" + str(sequenceN))
        stream.append("uint:32=" + str(typeByte))
        stream.append("uint:32=" + str(len(json_payload) + 8)) # + 4 (crc) + 4 (suffix)
        stream.append(json_payload)

        crc_value = binascii.crc32(stream.bytes) & 0xFFFFFFFF
        stream.append("uint:32=" + str(crc_value))
        stream.append("uint:32=43605")

        #_LOGGER.debug("Encoded: %s", stream.bytes.hex())

        return stream.bytes


    async def _decode(self, raw_message) -> Tuple[Any, ...]:
        stream = bitstring.ConstBitStream(raw_message)
        stream.bytepos = 8
        command = stream.read('uint:32')
        payload_length = stream.read('uint:32')

        return_code = stream.read('uint:32')
        payload_start = stream.bytepos

        if return_code & 0xFFFFFF00:
            payload_length -= 8 # - 4 (tail crc) - 4 (suffix)
            payload_start -= 4 # - 4 (return_code)
        else:
            payload_length -= 12 # - 4 (return_code) - 4 (tail crc) - 4 (suffix)

        payload_end = payload_start + payload_length
        payload = None

        if payload_length > 0:
            stream.bytepos = payload_end
            to_crc_length = stream.bytepos

            expected_crc = stream.read('uint:32')
            suffix = stream.read('bytes:4')

            stream.bytepos = 0
            actual_crc = binascii.crc32(stream.read('bytes:' + str(to_crc_length))) & 0xFFFFFFFF

            if actual_crc != expected_crc:
                _LOGGER.warning("Received message from %s failed CRC32 validation. Throwing out message.. Received %d. Expected %d", self._device_info["address"], actual_crc, expected_crc)
                return None

            stream.bytepos = payload_start

            payload_raw = None
            if self._device_info['version'] == '3.3':
                if command != COMMAND_DP_QUERY:
                    stream.bytepos += 15

                payload_encrypted = stream.read('bytes:' + str(payload_end - stream.bytepos))
                payload_raw = await self._cipher.decrypt(payload_encrypted, b64=False)
            else: # Old Version
                version_bytes = self._device_info['version'].encode('utf-8')
                version_test = stream.read("bytes:" + str(len(version_bytes)))

                if (version_test == version_bytes): # When the payload is prefixed with the version, the message is encrypted
                    stream.bytepos += 16 # Remove MD5 hash
                    payload_encrypted = stream.read('bytes:' + str(payload_end - stream.bytepos))
                    payload_raw = await self._cipher.decrypt(payload_encrypted, b64=True)
                else: # Unencrypted message
                    stream.bytepos -= len(version_bytes)
                    payload_raw = stream.read('bytes:' + str(payload_end - stream.bytepos))

            if payload_raw is None:
                raise Exception("Unable to decrypted / read payload.")

            payload = None
            try:
                payload = json.loads(payload_raw.decode('utf-8'))
            except Exception as err:
                _LOGGER.error("Unable to decode JSON: %s", payload_raw.decode('utf-8'))


        _LOGGER.debug("Received Command: %d. Payload: %r", command, payload)

        return command, payload
