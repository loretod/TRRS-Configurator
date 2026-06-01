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

# === Load config ===
try:
    import config
    cfg = config.CONFIG
    raw_config = cfg.get("modes", {})
    active_pins = cfg.get("active_pins", ["sleeve", "ring_1", "ring_2"])
    mode_switch_pin = cfg.get("mode_switch_pin", active_pins[0])
    MODE_CYCLE_HOLD = cfg.get("mode_cycle_hold", 1.0)
    splitter_type = cfg.get("splitter_type", "trrs")
except (ImportError, AttributeError):
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
    MODE_CYCLE_HOLD = 1.0
    splitter_type = "trrs"

# === Pin setup depends on splitter type ===
#
# trrs / headset: TIP = output low (ground), RING_1/RING_2/SLEEVE = inputs
# mono:           TIP = input (Switch 1), RING_1 = input (Switch 2),
#                 RING_2 and SLEEVE = output low (grounds)
#
tip = digitalio.DigitalInOut(board.TIP)

if splitter_type == "mono":
    # Mono (stereo -> 2x mono) Y-splitter that terminates in a 3-conductor
    # TRS (stereo) plug: Tip, Ring, Sleeve. The two switch jacks map to:
    #   white jack -> Tip   -> board.TIP    (Switch 1)
    #   red jack   -> Ring   -> board.RING_1 (Switch 2)
    #   both sleeves -> Sleeve -> ground
    # Because the TRS plug only grounds the SLEEVE conductor, both TIP and
    # RING_1 are clean, independent inputs. RING_2 and SLEEVE are driven low
    # as grounds. TIP is always the mode switch (a short press still fires
    # its normal HID action).
    active_pins = ["tip", "ring_1"]
    mode_switch_pin = "tip"
    tip.direction = digitalio.Direction.INPUT
    tip.pull = digitalio.Pull.UP
    # RING_2 and SLEEVE become grounds
    _ring2_gnd = digitalio.DigitalInOut(board.RING_2)
    _ring2_gnd.direction = digitalio.Direction.OUTPUT
    _ring2_gnd.value = False
    _sleeve_gnd = digitalio.DigitalInOut(board.SLEEVE)
    _sleeve_gnd.direction = digitalio.Direction.OUTPUT
    _sleeve_gnd.value = False
    # RING_1 is Switch 2 input
    # (set up below via PIN_MAP in the normal input-init loop)
else:
    # TIP is ground reference for all switches
    tip.direction = digitalio.Direction.OUTPUT
    tip.value = False

# === Map pin names to board pins (excludes tip — handled separately above) ===
PIN_MAP = {
    "sleeve": board.SLEEVE,
    "ring_1": board.RING_1,
    "ring_2": board.RING_2,
}

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

# === Init only the active input pins ===
# In mono mode active_pins is forced to ["tip", "ring_1"] above, so TIP
# (reused) and RING_1 (via PIN_MAP) are added as the two inputs.
inputs = {}
for pin_name in active_pins:
    if pin_name == "tip":
        inputs["tip"] = tip  # reuse already-initialised object
    elif pin_name in PIN_MAP:
        p = digitalio.DigitalInOut(PIN_MAP[pin_name])
        p.direction = digitalio.Direction.INPUT
        p.pull = digitalio.Pull.UP
        inputs[pin_name] = p

num_modes = len(raw_config)

# === HID action dispatcher ===
# All actions fire on RELEASE only (is_press=False) to prevent OS key-repeat
# during long holds, e.g. while the mode-switch hold timer is running.
def do_action(action, is_press):
    if not is_press:
        return  # release (kbd/mouse already released unconditionally in the loop)
    t = action.get("type")
    if t == "keyboard":
        codes = [getattr(Keycode, k, None) for k in action.get("keys", [])]
        codes = [c for c in codes if c is not None]
        if codes:
            kbd.press(*codes)
    elif t == "consumer":
        code = getattr(ConsumerControlCode, action.get("code", ""), None)
        if code:
            cc.send(code)
    elif t == "mouse":
        btn_map = {
            "LEFT_BUTTON":   Mouse.LEFT_BUTTON,
            "RIGHT_BUTTON":  Mouse.RIGHT_BUTTON,
            "MIDDLE_BUTTON": Mouse.MIDDLE_BUTTON,
        }
        btn = btn_map.get(action.get("button", ""), Mouse.LEFT_BUTTON)
        mouse.press(btn)

# === Main State & Loop ===
mode = 0
pin_states = {name: False for name in inputs}
pixel.fill(MODE_COLORS[mode % len(MODE_COLORS)])

# Mode cycling: hold the designated mode_switch_pin
mode_pin_held_since = None
mode_pin_was_cycled = False  # prevent HID action firing on the same press that cycled mode

# === Startup settling ===
# Wait until the mode switch pin is released before entering the main loop.
# Only checks the mode switch pin — other pins (e.g. RING_1 with a TS plug
# inserted) may float or short unpredictably and should not block startup.
time.sleep(0.2)
if mode_switch_pin in inputs:
    while not inputs[mode_switch_pin].value:
        time.sleep(0.05)
# Sync pin_states to actual pin readings so the loop starts clean
pin_states = {name: not pin.value for name, pin in inputs.items()}

while True:
    current_states = {name: not pin.value for name, pin in inputs.items()}

    # === Multi-pin suppression ===
    # Only suppress if multiple pins are NEWLY pressed this tick (state changed
    # from not-pressed to pressed). Pins that are continuously held low (e.g.
    # RING_1 shorted by a TS plug barrel touching the contact) are ignored so
    # they don't suppress legitimate presses on the active switch pin.
    newly_pressed = [name for name, v in current_states.items()
                     if v and not pin_states[name]]
    if len(newly_pressed) > 1:
        for name in current_states:
            if name != mode_switch_pin:
                current_states[name] = False

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
                kbd.release_all()  # release immediately so OS never triggers key-repeat
        else:
            mode_pin_held_since = None
            mode_pin_was_cycled = False

    # === Handle each active pin independently ===
    for pin_name, is_pressed in current_states.items():
        if is_pressed != pin_states[pin_name]:
            # Always release HID on any pin release to prevent stuck keys/buttons,
            # regardless of whether the action itself will fire.
            if not is_pressed:
                kbd.release_all()
                mouse.release_all()
            # If this pin's hold triggered a mode cycle, suppress the HID action
            # on release so it doesn't also fire the pin's normal action.
            if pin_name == mode_switch_pin and mode_pin_was_cycled:
                pin_states[pin_name] = is_pressed
                continue
            action = raw_config.get(str(mode), {}).get(pin_name, {})
            if action:
                do_action(action, is_pressed)
            pin_states[pin_name] = is_pressed

    time.sleep(0.01)
