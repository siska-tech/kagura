import hashlib,binascii,json,sys
for path in ('/kagura_dma_pack_viper.mpy','/kagura_fifo_xfer_viper.mpy'):
 h=hashlib.sha256();size=0
 with open(path,'rb') as file:
  while True:
   block=file.read(512)
   if not block:break
   h.update(block);size+=len(block)
 print('TILEFB '+json.dumps(dict(event='transport_native_helper',path=path,bytes=size,sha256=binascii.hexlify(h.digest()).decode())))
c=kagura_console
assert c.screen is not None and c._attached
assert c.screen.device.abi==(0,6)
c.screen.device.check_errors()
print('TILEFB '+json.dumps(dict(event='transport_console_checked',abi=list(c.screen.device.abi),error=0,console_active=c._attached,mpy_arch=sys.implementation._mpy)))
