"""Quick rapid-press test for AnalogKeypad.
Run from REPL:  import test_buttons
"""
import time
from buttons import AnalogKeypad

kp = AnalogKeypad(33)

print("=== Rapid Press Test ===")
print("Quickly press any button multiple times.")
print("Press Ctrl+C to stop.\n")

count = {"up": 0, "down": 0, "ok": 0, "back": 0}
try:
    while True:
        event = kp._event()
        if event is not kp.NONE:
            count[event] = count.get(event, 0) + 1
            print(f"  {event:6s}  (total: up={count['up']} dn={count['down']} ok={count['ok']} bk={count['back']})")
        time.sleep_ms(30)  # 30ms poll = fast response
except KeyboardInterrupt:
    total = sum(count.values())
    print(f"\n=== Result: {total} events ===")
    for btn in ["up", "down", "ok", "back"]:
        if count[btn] > 0:
            print(f"  {btn:6s}: {count[btn]}")
