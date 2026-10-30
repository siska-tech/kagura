import gc,sys,binascii,json,os
if 'kagura_console' in globals() and kagura_console is not None:
 kagura_console.close()
 kagura_console=None
_session=None
sys.modules.pop('transport_bench_20261030',None)
globals().pop('transport_bench_20261030',None)
gc.collect()
from kagura1200.console import start as start_transport_console
_candidate=start_transport_console(mode='qspi',baudrate=5000000)
assert _candidate.screen is not None, repr(_candidate.last_error)
assert _candidate.screen.device.abi==(0,6)
_candidate.screen.device.check_errors()
old=open('/boot.py','rb').read()
assert old.count(b'from kagura.console import start')==1
new=old.replace(b'from kagura.console import start',b'from kagura1200.console import start')
backup='/boot.pre-transport-20261030.py'
assert 'boot.pre-transport-20261030.py' not in os.listdir('/')
with open(backup,'wb') as file:file.write(old)
with open('/boot.transport-new.py','wb') as file:file.write(new)
os.rename('/boot.transport-new.py','/boot.py')
assert open('/boot.py','rb').read()==new
assert open(backup,'rb').read()==old
kagura_console=_candidate
machine=__import__('machine')
sm=kagura_console.screen.device.transport._sm_id
clkdiv=machine.mem32[0x50200000+(sm//4)*0x100000+0xc8+(sm%4)*0x18]
print('TILEFB '+json.dumps(dict(event='transport_console_restored',abi=list(kagura_console.screen.device.abi),height=kagura_console.screen.device.height,error=kagura_console.screen.device.read_reg(0x17),console_active=kagura_console._attached,baudrate=kagura_console.screen.device.transport.baudrate,clock_hz=machine.freq(),pio_clkdiv_register=clkdiv,boot_backup=backup,boot_original_hex=binascii.hexlify(old).decode())))
