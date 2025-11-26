import asyncio
import machine
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

        self.tsf = asyncio.ThreadSafeFlag()

        # 4000 pulses per kWh
        self.pulse_count = 0
        self.pulse_delta_ms = 0

        self.pulse_ticks = 0
        self.pulse_prev_ticks = 0

    # Interrupt callback
    def isr_callback(self, src):
        self.pulse_ticks = time.ticks_ms()
        self.tsf.set()

    # Handle pulse timing data from ISR
    async def pulse_counter(self):
        while True:
            await self.tsf.wait()
            self.led.toggle()

            self.pulse_count += 1

            self.pulse_delta_ms = time.ticks_diff(
                self.pulse_ticks, self.pulse_prev_ticks
            )
            self.pulse_prev_ticks = self.pulse_ticks

    # Report cumulative energy comsumed (in Watt hours)
    async def energy_mon(self, report_interval):
        try:
            with open("/pulse_count.txt", "r") as f:
                pcount = f.read()
                self.pulse_count = int(pcount)
        except (OSError, ValueError):
            self.pulse_count = 0
        self.stored_pulse_count = self.pulse_count

        while True:
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
        while True:
            if self.pulse_delta_ms > 0:
                # One pulse per second = 900 Watts
                power = int(900 / (self.pulse_delta_ms / 1000))
                self.mqtt.publish(b"metermon/power_w", str(power).encode())

            await asyncio.sleep(report_interval)

    async def run(self, energy_interval, power_interval):
        t1 = asyncio.create_task(self.pulse_counter())
        t2 = asyncio.create_task(self.energy_mon(energy_interval))
        t3 = asyncio.create_task(self.power_mon(power_interval))

        await asyncio.gather(t1, t2, t3)


mqtt = MQTTClient(
    "metermon_client",
    "homeassistant.local",
    user="mqtt",
    password=secrets.MQTT_PASSWORD,
)
mqtt.connect()

led = machine.Pin("LED", machine.Pin.OUT)
pulse_pin = machine.Pin(5, machine.Pin.IN)

meter_mon = MeterMonitor(mqtt, led)
pulse_pin.irq(meter_mon.isr_callback, trigger=machine.Pin.IRQ_RISING, hard=True)
# timer = Timer(freq=2, callback=meter_mon.isr_callback, hard=True)

asyncio.run(meter_mon.run(energy_interval=300, power_interval=5))
