# Async Tuya LAN Control

Integration with [TuyaCloud](https://www.tuya.com/cloud) smart home devices using local LAN control and Python's asyncio library. This library was thrown together in a week to support some cheap bulbs that I bought expecting to use [Tuya-Convert](https://github.com/ct-Open-Source/tuya-convert) on, but got hit with the [latest firmware](https://github.com/ct-Open-Source/tuya-convert/wiki/Collaboration-document-for-PSK-Identity-02) version from Tuya. At the time, I couldn't find any Python Tuya libraries supporting asyncio for local push use in [Home Assistant](https://www.home-assistant.io/).

I only have tested Tuya lights with this library as that is the only device I own, I will include classes for the additional devices, but they will need to be tested to confirm usage.

## Example Usage

This library requires the device ID and the local key for the device you want to control. I found it easiest to snag the local key from an [older version of the Smart Life app](https://www.apkmirror.com/apk/tuya-inc/smart-life-smart-living/)'s preferences.xml on a rooted Android phone. There are other methods you can read about [here](https://github.com/codetheweb/tuyapi/blob/master/docs/SETUP.md).

```python
from aiotuyalan import TuyaLight
import asyncio

IP = '192.168.1.26'
LOCAL_KEY = 'fffff00000ffffff'
DEVICE_ID = 'ffff000fff00f0f0f000'

async def main():

    loop = asyncio.get_running_loop()
    device = TuyaLight(loop, IP, DEVICE_ID, LOCAL_KEY, version='3.3')

    async def on_update():
        print("Received device update.")
        await device.set_color_temp(40)
        await device.set_brightness(255)
        await device.disconnect()

    async def on_stop():
        print("Disconnected from device.")
        loop.stop()

    await device.set_on_update(on_update)
    await device.set_on_stop(on_stop)

    while True:
        try:
            await device.connect()
            break
        except Exception as err:
            print("Error occcured during connection: ", err)
            print("Trying again in  5 seconds...")
            await asyncio.sleep(5)

    print("Connected to device!")

loop = asyncio.get_event_loop()
try:
    asyncio.ensure_future(main())
    loop.run_forever()
except KeyboardInterrupt:
    pass
finally:
    loop.close()
```
