import os,hashlib,binascii,json
backup='/boot.transport-bench-runtime.py'
flag='/transport-bench.skip'
if 'boot.transport-bench-runtime.py' in os.listdir('/'):
 original=open(backup,'rb').read()
 assert binascii.hexlify(hashlib.sha256(original).digest()).decode()=='301d9cc8067d001cb812be43f9bccbd183abeacd514d21347f725a7989c497f0'
 with open('/boot.transport-tmp.py','wb') as file:file.write(original)
 os.rename('/boot.transport-tmp.py','/boot.py')
 assert open('/boot.py','rb').read()==original
 os.remove(backup)
 if 'transport-bench.skip' in os.listdir('/'):
  assert open(flag,'rb').read()==b'KAGURA-TRANSPORT-BENCH-ONCE'
  os.remove(flag)
print('TILEFB '+json.dumps(dict(event='transport_boot_bytes_restored',sha256=binascii.hexlify(hashlib.sha256(open('/boot.py','rb').read()).digest()).decode(),expected_sha256='301d9cc8067d001cb812be43f9bccbd183abeacd514d21347f725a7989c497f0')))
