import os,hashlib,binascii,json
backup='/boot.transport-bench-runtime.py'
flag='/transport-bench.skip'
original=open('/boot.py','rb').read()
assert binascii.hexlify(hashlib.sha256(original).digest()).decode()=='301d9cc8067d001cb812be43f9bccbd183abeacd514d21347f725a7989c497f0'
assert 'boot.transport-bench-runtime.py' not in os.listdir('/')
assert 'transport-bench.skip' not in os.listdir('/')
with open(backup,'wb') as file:file.write(original)
wrapper=b"# Temporary benchmark clean boot; normal boot runs after the one-shot flag.\nimport os as _transport_boot_os\nif 'transport-bench.skip' in _transport_boot_os.listdir('/'):\n    _transport_boot_os.remove('/transport-bench.skip')\n    print('TRANSPORT_CLEAN_BOOT')\nelse:\n"+b''.join(b'    '+line for line in original.splitlines(True))
with open('/boot.transport-tmp.py','wb') as file:file.write(wrapper)
os.rename('/boot.transport-tmp.py','/boot.py')
with open(flag,'wb') as file:file.write(b'KAGURA-TRANSPORT-BENCH-ONCE')
print('TILEFB '+json.dumps(dict(event='transport_clean_boot_prepared',original_sha256='301d9cc8067d001cb812be43f9bccbd183abeacd514d21347f725a7989c497f0',temporary=True)))
