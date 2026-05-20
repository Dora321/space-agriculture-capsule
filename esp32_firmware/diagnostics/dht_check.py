"""Trace temp/hum through the full code path"""
import sensors
import config

print("=== Init sensors ===")
sensors.init()

print("\n=== Read all sensors ===")
data = sensors.read_all()
print(f"read_all result: {data}")

print(f"\nTemp = {data['temperature']}")
print(f"Hum  = {data['humidity']}")
print(f"Soil = {data['soil_moisture']}")
print(f"Light= {data['light_level']}")
print(f"Plant= {data['plant_type']}")

print("\n=== Check display call ===")
import display
display.init()
display.show_idle(
    data['soil_moisture'],
    data['light_level'],
    data['plant_type'],
    data['temperature'],
    data['humidity']
)
print("show_idle called with temp/hum - check screen!")
