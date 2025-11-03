import asyncio
from machine import Pin
import micropython
import time
from umqtt.robust import MQTTClient

import secrets

# For ISR debugging
micropython.alloc_emergency_exception_buf(100)


class MeterMonitor:
    def __init__(self, mqtt, led):
        self.mqtt = mqtt
        self.led = led

        # 4000 pulses per kWh
        self.pulse_count = 0
        self.pulse_delta_ms = 0
        self.pulse_prev_ticks = 0

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
            self.mqtt.publish(b"metermon/cumulative_wh", str(wh).encode())

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
                self.mqtt.publish(b"metermon/power_w", str(power).encode())

            await asyncio.sleep(report_interval)

    async def run(self, energy_interval, power_interval):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.energy_mon(energy_interval))
            tg.create_task(self.power_mon(power_interval))


mqtt = MQTTClient(
    "metermon_client",
    "homeassistant.local",
    user="mqtt",
    password=secrets.MQTT_PASSWORD,
)
while 1:
    try:
        mqtt.connect()
        break
    except OSError:
        print("Trying to connect to MQTT broker...")
        time.sleep(1)

led = Pin("LED", Pin.OUT)
pulse_pin = Pin(5, Pin.IN)

meter_mon = MeterMonitor(mqtt, led)
pulse_pin.irq(meter_mon.isr_callback, trigger=Pin.IRQ_RISING, hard=True)
# timer = Timer(freq=2, callback=meter_mon.isr_callback, hard=True)

asyncio.run(meter_mon.run(energy_interval=300, power_interval=5))
