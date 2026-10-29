import shooter,time
import kagura_dma_pack as pack
raw=kagura_console.screen.device.transport
original_words=raw._words
saved=(pack.viper_pack,pack.viper_pack32)
try:
    pack.viper_pack=pack.viper_pack32=None
    result=shooter.run(console=kagura_console,mode='HEAVY',frames=30,target_fps=0,
                       renderer='python',dma='accelerated',dma_chunk=512,input_fn=lambda:0,report=False)
    print('FALLBACK_EFFECTIVE',result['dma_effective'],result['acceleration_reason'])
    time.sleep_ms(10)
    print('FALLBACK_FRAMES_ERRORS',result['frames'],result['audio_errors'],result['error_count'],result['cleanup_errors'])
    time.sleep_ms(10)
    print('FALLBACK_UNTOUCHED',raw._words is original_words,all(name not in raw.__dict__ for name in ('_xfer','write','readinto','_xfer_dma')))
    time.sleep_ms(10)
finally:
    pack.viper_pack,pack.viper_pack32=saved
print('FALLBACK_REPL',not kagura_console.paused)
