import os
p='/lib/kaguragap'
if 'kaguragap' in os.listdir('/lib'):
 names=os.listdir(p)
 assert all(n in ['__init__.py', 'regs.py', 'device.py', 'video.py', 'audio.py', 'transport_rp2.py', 'dma_pack.py', 'fifo_xfer.py', 'acceleration.py', 'framebuffer.py', 'framebuffer_viper.py', 'framebuffer_diagnostic.py', 'framebuffer_benchmark.py', 'framebuffer_viper_cases.py', 'framebuffer_viper_validation.py', 'framebuffer_shapes.py'] for n in names)
 for n in names:os.remove(p+'/'+n)
 os.rmdir(p)
s=os.statvfs('/')
print('GAP_UPLOAD_CLEANED_FREE',s[0]*s[3])
