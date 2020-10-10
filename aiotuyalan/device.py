import logging
import asyncio

from .lib.client import TuyaClient, COMMAND_DP_QUERY, COMMAND_STATUS, COMMAND_CONTROL

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("TuyaDevice")

class TuyaDevice:

    DPS_INDEX_ON = '1'

    def __init__(self, event_loop, address, id, local_key, port=6668, version='3.1', timeout=30, gw_id=None):
        self._event_loop = event_loop
        self._connection = None
        self._connect_timeout = timeout
        self._on_stop_callback = None
        self._on_update_callback = None
        self._device_info = {
            "address": address,
            "port": port,
            "id": id,
            "gw_id": gw_id,
            "version": version
        }
        self._local_key = local_key
        self._dps: None

        if self._device_info["gw_id"] is None:
            self._device_info["gw_id"] = id
        if len(local_key) != 16:
            raise ValueError('Local key length should be 16 characters!')


    async def connect(self):
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

            if connected and self._on_stop_callback is not None:
                await self._on_stop_callback()

        async def __on_payload(command, payload):
            await self._on_payload(command, payload)

        self._connection = TuyaClient(self._device_info, self._local_key, self._event_loop, _on_stop, __on_payload)

        try:
            await self._connection.connect()
        except Exception as e:
            await _on_stop()
            raise

        connected = True

        await self.update()

    async def disconnect(self):
        if self._connection is None:
            raise Exception("Attempt to disconnect when not connected!")

        await self._connection.stop()

    async def set_on_stop(self, on_stop):
        self._on_stop_callback = on_stop

    async def set_on_update(self, on_update):
        self._on_update_callback = on_update

    async def update(self):
        await self._connection.send(COMMAND_DP_QUERY, {})

    async def set_enabled(self, enabled) -> None:
        if self._dps is None:
            raise Exception("Unable to set properties until first update is made to device.")
        self._dps[TuyaDevice.DPS_INDEX_ON] = enabled
        await self._connection.send(COMMAND_CONTROL, {TuyaDevice.DPS_INDEX_ON: enabled})

    async def _on_payload(self, command, payload) -> None:
        if command == COMMAND_DP_QUERY:
            self._dps = payload['dps'] # Replace entire dps
        elif command == COMMAND_STATUS:
            self._dps = {**self._dps, **payload['dps']}

        print("hi")

        if self._on_update_callback:
            await self._on_update_callback()
