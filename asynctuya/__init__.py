import logging
import asyncio

from .lib.client import TuyaClient, COMMAND_DP_QUERY

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("TuyaDevice")

class TuyaDevice(object):

    def __init__(self, event_loop, address, id, local_key, port=6668, version='3.1', timeout=30, gw_id=None):
        self._event_loop = event_loop
        self._connection = None
        self._connect_timeout = timeout
        self._device_info = {
            "address": address,
            "port": port,
            "id": id,
            "gw_id": gw_id,
            "version": version
        }
        self._local_key = local_key
        self._dps: {}

        if self._device_info["gw_id"] is None:
            self._device_info["gw_id"] = id
        if len(local_key) != 16:
            raise ValueError('Local key length should be 16 characters!')


    async def connect(self, on_stop=None):
        if self._connection is not None:
            raise Exception("Attempt to connect while already connected!")

        connected = False
        stopped = False

        async def _on_stop():
            nonlocal stopped
            if stopped:
                return
            stopped = True
            self._connection = None

            if connected and on_stop is not None:
                await on_stop()

        self._connection = TuyaClient(self._device_info, self._local_key, self._event_loop, _on_stop, self._on_payload)

        try:
            await self._connection.connect()
        except Exception as e:
            await _on_stop()
            raise

        connected = True

        await self.update()

    async def update(self):
        await self._connection.send(COMMAND_DP_QUERY, {})

    async def _on_payload(self, command, payload):
        pass
