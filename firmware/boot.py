import usb_cdc

# Second CDC serial ("data") carries the LED protocol from the host daemon
# without fighting over the REPL console on the first one.
usb_cdc.enable(console=True, data=True)
