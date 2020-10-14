import colorsys
import bitstring

from typing import Optional, Any, Dict, Tuple
from .device import TuyaDevice
from .lib.client import COMMAND_CONTROL, COMMAND_DP_QUERY, COMMAND_STATUS

class TuyaLight(TuyaDevice):

    DPS_INDEX_MODE = '2'
    DPS_INDEX_BRIGHTNESS = '3'
    DPS_INDEX_COLORTEMP = '4'
    DPS_INDEX_COLOR = '5'
    DPS_INDEX_PRESENT_SCENE = '6'
    DPS_INDEX_CUSTOM_SCENE_1_PROPERTIES = '7'
    DPS_INDEX_CUSTOM_SCENE_2_PROPERTIES = '8'
    DPS_INDEX_CUSTOM_SCENE_3_PROPERTIES = '9'
    DPS_INDEX_CUSTOM_SCENE_4_PROPERTIES = '10'

    DPS_MODE_COLOR = 'colour'
    DPS_MODE_WHITE = 'white'
    DPS_MODE_SCENE_PRESET = 'scene'
    DPS_MODE_SCENE_CUSTOM_1 = 'scene_1'
    DPS_MODE_SCENE_CUSTOM_2 = 'scene_2'
    DPS_MODE_SCENE_CUSTOM_3 = 'scene_3'
    DPS_MODE_SCENE_CUSTOM_4 = 'scene_4'

    def __init__(self, event_loop, address, id, local_key, port=6668, version='3.1', timeout=30, gw_id=None):
        super(TuyaLight, self).__init__(event_loop, address, id, local_key, port=port, version=version, timeout=timeout, gw_id=gw_id)

        self._mode = None
        self._brightness = None
        self._color_temp = None
        self._color_hue = None
        self._color_saturation = None

    async def set_multiple(self, **kwargs):
        if self._dps is None:
            raise Exception("Unable to set properties until first update is made to device.")

        update_dps = {}
        if 'color_temp' in kwargs:
            update_dps = {**update_dps, **self._get_color_temp_dps(kwargs['color_temp'])}
            self._mode = TuyaLight.DPS_MODE_WHITE
            self._color_temp = kwargs['color_temp']
        if 'hs_color' in kwargs:
            update_dps = {**update_dps, **self._get_color_hs_dps(*kwargs['hs_color'])}
            self._mode = TuyaLight.DPS_MODE_COLOR
            self._hue = kwargs['hs_color'][0]
            self._saturation = kwargs['hs_color'][1]
        if 'brightness' in kwargs:
            update_dps = {**update_dps, **self._get_brightness_dps(kwargs['brightness'])}
            self._brightness = kwargs['brightness']
        if 'enabled' in kwargs:
            update_dps[TuyaDevice.DPS_INDEX_ON] = True
            self._dps[TuyaDevice.DPS_INDEX_ON] = True

        await self._connection.send(COMMAND_CONTROL, update_dps, encrypted=True)

    def get_mode(self) -> Optional[str]:
        return self._mode

    def get_brightness(self) -> Optional[int]:
        return self._brightness

    async def set_brightness(self, brightness, set_on=True) -> None:
        if self._dps is None:
            raise Exception("Unable to set properties until first update is made to device.")

        update_dps = self._get_brightness_dps(brightness)

        if set_on:
            update_dps[TuyaDevice.DPS_INDEX_ON] = True
            self._dps[TuyaDevice.DPS_INDEX_ON] = True

        self._brightness = brightness

        await self._connection.send(COMMAND_CONTROL, update_dps, encrypted=True)

    def _get_brightness_dps(self, brightness) -> Dict[str, Any]:

        if not 0 <= brightness <= 255:
            raise ValueError("Brighness value is out of bounds (0-255)")

        update_dps = {}
        if self._mode == TuyaLight.DPS_MODE_COLOR:
            red, green, blue = colorsys.hsv_to_rgb(self._color_hue / 360, self._color_saturation / 255, brightness / 255)
            rgb_hex = TuyaLight._rgb_to_hex(int(red * 255), int(green * 255), int(blue * 255))
            hsv_hex = TuyaLight._hsv_to_hex(self._color_hue, self._color_saturation, brightness)
            update_dps[TuyaLight.DPS_INDEX_COLOR] = rgb_hex + hsv_hex
        else:
            update_dps[TuyaLight.DPS_INDEX_BRIGHTNESS] = brightness

        return update_dps


    def get_color_temp(self) -> int:
        return self._color_temp


    async def set_color_temp(self, temp, set_on=True) -> None:
        if self._dps is None:
            raise Exception("Unable to set properties until first update is made to device.")

        update_dps = self._get_color_temp_dps(temp)

        self._mode = TuyaLight.DPS_MODE_WHITE
        self._color_temp = temp

        if set_on:
            update_dps[TuyaDevice.DPS_INDEX_ON] = True
            self._dps[TuyaDevice.DPS_INDEX_ON] = True

        await self._connection.send(COMMAND_CONTROL, update_dps, encrypted=True)

    def _get_color_temp_dps(self, temp) -> Dict[str, Any]:
        if not 0 <= temp <= 255:
            raise ValueError("Temp value is out of bounds (0-255)")

        return {
            TuyaLight.DPS_INDEX_MODE: TuyaLight.DPS_MODE_WHITE,
            TuyaLight.DPS_INDEX_COLORTEMP: temp
        }


    async def set_color_rgb(self, red, green, blue, set_on=True) -> None:
        if self._dps is None:
            raise Exception("Unable to set properties until first update is made to device.")
        if not 0 <= red <= 255:
            raise ValueError("RGB red value is out of bounds (0-255)")
        if not 0 <= green <= 255:
            raise ValueError("RGB green value is out of bounds (0-255)")
        if not 0 <= blue <= 255:
            raise ValueError("RGB blue value is out of bounds (0-255)")

        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)

        hue = int(hue * 255)
        saturation = int(saturation * 255)
        value = int(value * 255)

        rgb_hex = TuyaLight._rgb_to_hex(red, green, blue)
        hsv_hex = TuyaLight._hsv_to_hex(hue, saturation, value)

        update_dps = {
            TuyaLight.DPS_INDEX_MODE: TuyaLight.DPS_MODE_COLOR,
            TuyaLight.DPS_INDEX_COLOR: rgb_hex + hsv_hex
        }

        if set_on:
            update_dps[TuyaDevice.DPS_INDEX_ON] = True
            self._dps[TuyaDevice.DPS_INDEX_ON] = True

        self._mode = TuyaLight.DPS_MODE_COLOR
        self._color_hue = hue
        self._color_saturation = saturation
        self._brightness = value

        await self._connection.send(COMMAND_CONTROL, update_dps, encrypted=True)

    def get_color_hs(self) -> Optional[Tuple[int, int]]:
        return (self._color_hue, self._color_saturation)

    async def set_color_hs(self, hue, saturation, set_on=True) -> None:
        if self._dps is None:
            raise Exception("Unable to set properties until first update is made to device.")

        update_dps = self._get_color_hs_dps(hue, saturation)

        if set_on:
            update_dps[TuyaDevice.DPS_INDEX_ON] = True
            self._dps[TuyaDevice.DPS_INDEX_ON] = True

        self._mode = TuyaLight.DPS_MODE_COLOR
        self._hue = hue
        self._saturation = saturation

        await self._connection.send(COMMAND_CONTROL, update_dps, encrypted=True)

    def _get_color_hs_dps(self, hue, saturation) -> Dict[str, Any]:
        if not 0 <= hue <= 360:
            raise ValueError("Hue value %d is out of bounds (0-360)", hue)
        if not 0 <= saturation <= 255:
            raise ValueError("Saturation value %d is out of bounds (0-255)", saturation)

        red, green, blue = colorsys.hsv_to_rgb(hue / 360, saturation / 255, self._brightness / 255)

        rgb_hex = TuyaLight._rgb_to_hex(int(red * 255), int(green * 255), int(blue * 255))
        hsv_hex = TuyaLight._hsv_to_hex(hue, saturation, self._brightness)

        update_dps = {
            TuyaLight.DPS_INDEX_MODE: TuyaLight.DPS_MODE_COLOR,
            TuyaLight.DPS_INDEX_COLOR: rgb_hex + hsv_hex
        }

        return update_dps

    async def _on_payload(self, command, payload) -> None:

        if command == COMMAND_STATUS or command == COMMAND_DP_QUERY:
            dps = payload['dps']

            if TuyaLight.DPS_INDEX_MODE in dps:
                self._mode = dps[TuyaLight.DPS_INDEX_MODE]

            if TuyaLight.DPS_INDEX_BRIGHTNESS in dps and self._mode == TuyaLight.DPS_MODE_WHITE:
                self._brightness = dps[TuyaLight.DPS_INDEX_BRIGHTNESS]

            if TuyaLight.DPS_INDEX_COLORTEMP in dps:
                self._color_temp = dps[TuyaLight.DPS_INDEX_COLORTEMP]

            if TuyaLight.DPS_INDEX_COLOR in dps:
                hue, saturation, value = TuyaLight._hex_to_hsv(dps[TuyaLight.DPS_INDEX_COLOR])
                self._color_hue = hue
                self._color_saturation = saturation
                if self._mode == TuyaLight.DPS_MODE_COLOR:
                    self._brightness = value

        await super(TuyaLight, self)._on_payload(command, payload)

    @staticmethod
    def _rgb_to_hex(red, green, blue):
        stream = bitstring.BitStream()
        stream.append("uint:8=" + str(red))
        stream.append("uint:8=" + str(green))
        stream.append("uint:8=" + str(blue))

        return stream.bytes.hex()

    @staticmethod
    def _hsv_to_hex(hue, saturation, value):
        stream = bitstring.BitStream()
        stream.append("uint:16=" + str(hue))
        stream.append("uint:8=" + str(saturation))
        stream.append("uint:8=" + str(value))

        return stream.bytes.hex()

    @staticmethod
    def _hex_to_hsv(hex_str):
        stream = bitstring.ConstBitStream(hex='0x' + hex_str)
        stream.bytepos = 3
        return stream.readlist('uint:16, uint:8, uint:8')
