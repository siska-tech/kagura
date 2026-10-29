import shooter,time
for detail,meter in ((False,False),(False,True),(True,True)):
    print('OVERHEAD_CASE',detail,meter)
    shooter.run(console=kagura_console,mode='HEAVY',frames=400,target_fps=0,renderer='viper',dma='accelerated',dma_chunk=512,input_fn=lambda:0,profile=detail,instrument_transport=meter)
