import machine,time
import shooter
from kagura.audio import Audio
_uart=kagura_console.uart
_old_cr=machine.mem32[0x40034030]
_original_init=shooter.Game.initialize
_ctrl_timer=None
_ctrl_caught=False
def send_interrupt(timer):
 _uart.write(bytes((3,)))
def initialize(self):
 global _ctrl_timer
 _original_init(self)
 _ctrl_timer=machine.Timer(period=1200,mode=machine.Timer.ONE_SHOT,callback=send_interrupt,hard=False)
shooter.Game.initialize=initialize
machine.mem32[0x40034030]=_old_cr|0x80
try:
 try:
  shooter.run(console=kagura_console,mode='FULL',duration=8,report=False,renderer='viper',dma='accelerated',dma_chunk=512)
 except KeyboardInterrupt:
  _ctrl_caught=True
 print('CTRL_C_CAUGHT',_ctrl_caught)
 print('CTRL_C_CONSOLE_RESUMED',not kagura_console.paused)
 print('CTRL_C_CLEANUP',shooter.LAST_STATS['cleanup_errors'])
 _device=kagura_console.screen.device
 _audio=Audio(_device)
 print('CTRL_C_PCM_ACTIVE',bool((_audio.pcm_status(0)|_audio.pcm_status(1))&2))
 print('CTRL_C_PSG_ENABLED',any(_device.audio_read(ch*16+6)&1 for ch in range(6)))
 print('CTRL_C_FPGA_ERROR',_device.read_reg(0x17))
finally:
 if _ctrl_timer is not None:_ctrl_timer.deinit()
 shooter.Game.initialize=_original_init
 machine.mem32[0x40034030]=_old_cr

print('DMA_OVERRIDE_RESTORED',not ('_xfer_dma' in _device.transport.__dict__))


