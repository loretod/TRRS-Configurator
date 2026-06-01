CONFIG = {
  "version": 1,
  "splitter_type": "mono",
  "active_pins": [
    "tip",
    "ring_1"
  ],
  "mode_switch_pin": "tip",
  "mode_cycle_hold": 1,
  "modes": {
    "0": {
      "tip": {
        "type": "keyboard",
        "keys": [
          "A"
        ]
      },
      "ring_1": {
        "type": "keyboard",
        "keys": [
          "B"
        ]
      }
    },
    "1": {
      "tip": {
        "type": "consumer",
        "code": "PLAY_PAUSE"
      },
      "ring_1": {
        "type": "consumer",
        "code": "SCAN_NEXT_TRACK"
      }
    },
    "2": {
      "tip": {
        "type": "mouse",
        "button": "LEFT_BUTTON"
      },
      "ring_1": {
        "type": "mouse",
        "button": "RIGHT_BUTTON"
      }
    },
    "3": {
      "tip": {
        "type": "none"
      },
      "ring_1": {
        "type": "none"
      }
    }
  }
}
