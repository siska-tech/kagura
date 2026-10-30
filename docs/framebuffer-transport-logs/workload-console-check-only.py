import json
c=kagura_console
assert c.screen is not None and c._attached
assert c.screen.device.abi==(0,6)
c.screen.device.check_errors()
print('TILEFB '+json.dumps(dict(event='transport_console_restored',abi=list(c.screen.device.abi),height=c.screen.device.height,error=0,console_active=c._attached,no_boot_write=True)))
