import asyncio
import machine
import micropython
import network
import time
from umqtt.simple import MQTTClient

import secrets

# For ISR debugging
micropython.alloc_emergency_exception_buf(100)


class MeterMonitor:
    def __init__(self, wlan, mqtt, led):
        self.wlan = wlan
        self.mqtt = mqtt
        self.led = led

        # 4000 pulses per kWh
        self.pulse_count = 0
        self.pulse_delta_ms = 0
        self.pulse_prev_ticks = 0

    def connect(self):
        if not self.wlan.isconnected():
            print("re-connecting to network...")
            self.wlan.connect("cumulus-2g", secrets.WIFI_PASSWORD)
            while not self.wlan.isconnected():
                machine.idle()

            print("network config:", self.wlan.ipconfig("addr4"))

    # Interrupt callback
    def isr_callback(self, src):
        ticks = time.ticks_ms()

        self.pulse_count += 1
        self.led.toggle()

        self.pulse_delta_ms = time.ticks_diff(ticks, self.pulse_prev_ticks)
        self.pulse_prev_ticks = ticks

    # Report cumulative energy comsumed (in Watt hours)
    async def energy_mon(self, report_interval):
        try:
            with open("/pulse_count.txt", "r") as f:
                pcount = f.read()
                self.pulse_count = int(pcount)
        except (OSError, ValueError):
            self.pulse_count = 0
        self.stored_pulse_count = self.pulse_count

        while 1:
            wh = self.pulse_count // 4
            self.connect()
            self.mqtt.connect()
            self.mqtt.publish(b"metermon/cumulative_wh", str(wh).encode())
            self.mqtt.disconnect()

            if self.pulse_count - self.stored_pulse_count >= 4000:
                try:
                    with open("/pulse_count.txt", "w") as f:
                        f.write(str(self.pulse_count))
                except OSError:
                    print("Can't store pulse count")
                self.stored_pulse_count = self.pulse_count

            await asyncio.sleep(report_interval)

    # Report current power consumption (in Watts)
    async def power_mon(self, report_interval):
        while 1:
            if self.pulse_delta_ms > 0:
                # One pulse per second = 900 Watts
                power = int(900 / (self.pulse_delta_ms / 1000))
                self.connect()
                self.mqtt.connect()
                self.mqtt.publish(b"metermon/power_w", str(power).encode())
                self.mqtt.disconnect()

            await asyncio.sleep(report_interval)

    async def run(self, energy_interval, power_interval):
        t1 = asyncio.create_task(self.energy_mon(energy_interval))
        t2 = asyncio.create_task(self.power_mon(power_interval))

        await asyncio.gather(t1, t2)


wlan = network.WLAN(network.STA_IF)
mqtt = MQTTClient(
    "metermon_client",
    "homeassistant.local",
    user="mqtt",
    password=secrets.MQTT_PASSWORD,
)

led = machine.Pin("LED", machine.Pin.OUT)
pulse_pin = machine.Pin(5, machine.Pin.IN)

meter_mon = MeterMonitor(wlan, mqtt, led)
pulse_pin.irq(meter_mon.isr_callback, trigger=machine.Pin.IRQ_RISING, hard=True)
# timer = Timer(freq=2, callback=meter_mon.isr_callback, hard=True)

asyncio.run(meter_mon.run(energy_interval=300, power_interval=5))
