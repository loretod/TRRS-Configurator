import board
import digitalio
import neopixel
import time
import usb_hid
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.consumer_control_code import ConsumerControlCode
from adafruit_hid.mouse import Mouse

# === Load config.py ===
try:
    import config
    cfg = config.CONFIG
    raw_config = cfg.get("modes", {})
    active_pins = cfg.get("active_pins", ["sleeve", "ring_1", "ring_2"])
    mode_switch_pin = cfg.get("mode_switch_pin", active_pins[0])
    MODE_CYCLE_HOLD = cfg.get("mode_cycle_hold", 1.0)
    print("Config loaded from config.py")
except (ImportError, AttributeError):
    print("config.py not found or invalid — using defaults")
    raw_config = {
        "0": {
            "sleeve": {"type": "keyboard", "keys": ["ENTER"]},
            "ring_1": {"type": "keyboard", "keys": ["TAB"]},
            "ring_2": {"type": "keyboard", "keys": ["SPACE"]},
        },
        "1": {
            "sleeve": {"type": "consumer", "code": "PLAY_PAUSE"},
            "ring_1": {"type": "consumer", "code": "SCAN_NEXT_TRACK"},
            "ring_2": {"type": "consumer", "code": "SCAN_PREVIOUS_TRACK"},
        },
        "2": {
            "sleeve": {"type": "mouse", "button": "LEFT_BUTTON"},
            "ring_1": {"type": "mouse", "button": "RIGHT_BUTTON"},
            "ring_2": {"type": "mouse", "button": "MIDDLE_BUTTON"},
        },
    }
    active_pins = ["sleeve", "ring_1", "ring_2"]
    mode_switch_pin = "sleeve"
    MODE_CYCLE_HOLD = 1.0  # seconds to hold mode switch before cycling

# === LED colors per mode ===
MODE_COLORS = [
    (0, 0, 255),    # Blue
    (0, 255, 0),    # Green
    (255, 0, 255),  # Magenta
    (255, 200, 0),  # Yellow
]

# === HID Hardware init ===
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.1)
kbd = Keyboard(usb_hid.devices)
cc = ConsumerControl(usb_hid.devices)
mouse = Mouse(usb_hid.devices)

# === TIP pin as output-low (acts as ground for switches) ===
tip = digitalio.DigitalInOut(board.TIP)
tip.direction = digitalio.Direction.OUTPUT
tip.value = False  # Pull to ground

# === Map pin names to board pins ===
PIN_MAP = {
    "sleeve": board.SLEEVE,
    "ring_1": board.RING_1,
    "ring_2": board.RING_2,
}

# === Init only the active input pins ===
inputs = {}
for pin_name in active_pins:
    if pin_name in PIN_MAP:
        p = digitalio.DigitalInOut(PIN_MAP[pin_name])
        p.direction = digitalio.Direction.INPUT
        p.pull = digitalio.Pull.UP
        inputs[pin_name] = p

num_modes = len(raw_config)

# === HID action dispatcher ===
def do_action(action, is_press):
    t = action.get("type")
    if t == "keyboard":
        codes = [getattr(Keycode, k, None) for k in action.get("keys", [])]
        codes = [c for c in codes if c is not None]
        if is_press:
            kbd.press(*codes)
        else:
            kbd.release_all()
    elif t == "consumer" and is_press:
        code = getattr(ConsumerControlCode, action.get("code", ""), None)
        if code:
            cc.send(code)
    elif t == "mouse" and is_press:
        btn_map = {
            "LEFT_BUTTON": Mouse.LEFT_BUTTON,
            "RIGHT_BUTTON": Mouse.RIGHT_BUTTON,
            "MIDDLE_BUTTON": Mouse.MIDDLE_BUTTON,
        }
        btn = btn_map.get(action.get("button", ""), Mouse.LEFT_BUTTON)
        mouse.click(btn)

# === Main State & Loop ===
mode = 0
pin_states = {name: False for name in inputs}
pixel.fill(MODE_COLORS[mode % len(MODE_COLORS)])

# Mode cycling: hold the designated mode_switch_pin
mode_pin_held_since = None
mode_pin_was_cycled = False  # prevent HID action firing on the same press that cycled mode

while True:
    current_states = {name: not pin.value for name, pin in inputs.items()}

    # === Mode switch hold logic ===
    if mode_switch_pin in current_states:
        ms_pressed = current_states[mode_switch_pin]

        if ms_pressed:
            if mode_pin_held_since is None:
                mode_pin_held_since = time.monotonic()
                mode_pin_was_cycled = False
            elif not mode_pin_was_cycled and (time.monotonic() - mode_pin_held_since >= MODE_CYCLE_HOLD):
                mode = (mode + 1) % num_modes
                pixel.fill(MODE_COLORS[mode % len(MODE_COLORS)])
                mode_pin_was_cycled = True
        else:
            mode_pin_held_since = None
            mode_pin_was_cycled = False

    # === Handle each active pin independently ===
    for pin_name, is_pressed in current_states.items():
        if is_pressed != pin_states[pin_name]:
            # Skip HID action on release if this press was consumed by a mode cycle
            if pin_name == mode_switch_pin and mode_pin_was_cycled:
                pin_states[pin_name] = is_pressed
                continue
            action = raw_config.get(str(mode), {}).get(pin_name, {})
            if action:
                do_action(action, is_pressed)
            pin_states[pin_name] = is_pressed

    time.sleep(0.01)
