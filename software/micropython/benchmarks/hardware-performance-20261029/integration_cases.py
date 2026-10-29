import shooter
for mode,load,sprites in (('BASE','STRESS',64),('PSG','STRESS',64),('PCM','STRESS',64),('FULL','STRESS',64),('FULL','EXTREME',128)):
    print('INTEGRATION_CASE',mode,load,sprites)
    shooter.run(console=kagura_console,mode=mode,load=load,sprites=128,frames=400,target_fps=0,renderer='viper',dma='accelerated',dma_chunk=512,input_fn=lambda:0,profile=True)

