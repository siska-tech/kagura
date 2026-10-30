# SPDX-License-Identifier: Apache-2.0
"""Plot on-device records, not host execution speed (requires matplotlib)."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(__file__).resolve().parents[1]
data=json.loads((root/'docs/framebuffer-transport-results.json').read_text(encoding='utf-8'))
rows=[r for r in data['current_run']['measurements'] if r.get('event')=='transport_micro']
fig,axes=plt.subplots(1,2,figsize=(11,4.8),layout='constrained')
for layout in ('contiguous','dispersed','narrow_rect','boundary','compact_rect'):
    selected=sorted((r for r in rows if r['layout']==layout),key=lambda r:r['tiles'])
    x=[r['tiles'] for r in selected]
    median=[r['timing']['flush']['median_us']/1000 for r in selected]
    upper=[max(0,r['timing']['flush']['p95_us']/1000-m) for r,m in zip(selected,median)]
    axes[0].errorbar(x,median,yerr=[[0]*len(x),upper],marker='.',capsize=2,label=layout)
    nonzero=[r for r in selected if r['last_flush']['bytes']]
    axes[1].plot([r['tiles'] for r in nonzero],
                 [r['last_flush']['bytes']/r['timing']['transfer']['mean_us'] for r in nonzero],
                 marker='.',label=layout)
axes[0].set(xlabel='Dirty tiles',ylabel='Host flush (ms), log scale',yscale='log',
            title='Median and p95; 30 samples/case, PCM 2ch')
axes[1].axhline(2,ls='--',color='0.4',lw=1,label='PIO queued limit (calculated)')
axes[1].set(xlabel='Dirty tiles',ylabel='Payload / host transfer API time (MB/s)',yscale='log',
            title='Includes address setup and error checks')
for ax in axes:
    ax.grid(True,which='both',alpha=.2)
    ax.legend(fontsize=8)
fig.suptitle('RP2040 125 MHz / MicroPython 1.26 / QSPI 5 MHz / ABI 0.6 / Viper')
fig.supxlabel('0..1024 and 1200 tiles were acquired in separate firmware recovery phases; see JSON.',fontsize=9)
dest=root/'docs/images/framebuffer-transport-baseline'
fig.savefig(dest.with_suffix('.svg'))
fig.savefig(root/'build/transport-analysis/framebuffer-transport-baseline.png',dpi=140)
print(dest.with_suffix('.svg'))
