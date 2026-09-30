import board
import digitalio
import storage
import usb_cdc

# Normal boots expose only the HID keyboard and the LED "data" serial port.
# The CIRCUITPY drive and REPL console are both ways for anything on the
# host to reprogram the pad into a device that types arbitrary keystrokes,
# so they stay off unless you ask for them.
#
# Maintenance mode: hold key 0 while plugging the pad in (or pressing reset)
# to get the CIRCUITPY drive and REPL back for flashing/debugging.
key0 = digitalio.DigitalInOut(board.SW0)
key0.switch_to_input(pull=digitalio.Pull.UP)
maintenance = not key0.value  # switches pull the pin low when pressed
key0.deinit()

if maintenance:
    # Second CDC serial ("data") carries the LED protocol from the host
    # daemon without fighting over the REPL console on the first one.
    usb_cdc.enable(console=True, data=True)
else:
    storage.disable_usb_drive()
    usb_cdc.enable(console=False, data=True)
