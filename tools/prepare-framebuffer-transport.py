# SPDX-License-Identifier: Apache-2.0
"""Prepare a RAM-only raw-REPL workload; no Pico filesystem writes here.

Execute with mpremote raw-paste after ABI 0.6 configuration.
Existing isolated SDK files must match the previously verified deployment.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repetitions',type=int,default=30)
    parser.add_argument('--sdk',default='kagurafbx')
    parser.add_argument('--deployment-manifest',type=Path,default=ROOT/'docs/framebuffer-primitives-results.json')
    parser.add_argument('--phase',choices=('all','scenes','remaining','finish','rectangles','fullblit'),default='all')
    parser.add_argument('--independent-full-source',action='store_true',
                        help='Reserve an additional 38400 bytes; may exceed RP2040 memory/layout limits')
    parser.add_argument('--output',type=Path,default=ROOT/'build/transport-analysis/run.py')
    args=parser.parse_args()
    if not 10<=args.repetitions<=100:parser.error('repetitions 10..100')
    if not args.sdk.isidentifier():parser.error('sdk must be a package identifier')
    if args.phase=='fullblit' and not args.independent_full_source:
        parser.error('fullblit requires --independent-full-source')
    prior=json.loads(args.deployment_manifest.read_text(encoding='utf-8-sig'))
    expected={}
    for record in prior['deployed']:
        source=ROOT/record['source']
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if digest!=record['sha256']:raise SystemExit('source differs from isolated SDK: '+str(source))
        expected[record['remote']]=digest
    prelude='''import sys, gc, hashlib, binascii
_fb_closed_console=globals().get('kagura_console')
if _fb_closed_console is not None:
    _fb_closed_console.close()
    for _fb_alias in ('kagura_console','_candidate','c','_c'):
        if globals().get(_fb_alias) is _fb_closed_console:globals()[_fb_alias]=None
_fb_closed_console=None
# The migrated boot uses a filesystem SDK. Evict its closed code cache so
# two complete SDK namespaces do not consume the RP2040 heap together.
_fb_boot_module=sys.modules.get('kagura1200.console')
if _fb_boot_module is not None:
    for _fb_alias in ('start','start_transport_console'):
        if globals().get(_fb_alias) is _fb_boot_module.start:globals().pop(_fb_alias)
_fb_boot_module=None
for _fb_module_name in tuple(sys.modules):
    if _fb_module_name=='kagura1200' or _fb_module_name.startswith('kagura1200.'):
        sys.modules.pop(_fb_module_name)
__import__('time').sleep_ms(30)
if '_session' in globals():_session=None
gc.collect()
sys.path.insert(0, '/fbx')
for path, expected in EXPECTED.items():
    h=hashlib.sha256()
    with open(path,'rb') as file:
        while True:
            block=file.read(512)
            if not block:break
            h.update(block)
    assert binascii.hexlify(h.digest()).decode()==expected, path
print('TRANSPORT_SDK_HASHES_PASS',len(EXPECTED))
del h, block
gc.collect()
'''.replace('EXPECTED',repr(expected),1)
    # Only replace the first EXPECTED (the loop expression), not the log count.
    prelude=prelude.replace('len(EXPECTED)',str(len(expected)))
    reserve=("_full_scene_source=bytearray(38400)\nfor _fb_source_i in range(38400):\n    _full_scene_source[_fb_source_i]=(_fb_source_i*73+(_fb_source_i>>7)*29+(_fb_source_i>>11)*17)&255\ngc.collect()\n"
             if args.independent_full_source else '_full_scene_source=None\n')
    prelude+=reserve
    source=(ROOT/'software/micropython/examples/framebuffer_transport_benchmark.py').read_text()
    action=('run(_session,REPETITIONS,full_source=_full_scene_source)' if args.phase=='all' else
            "_session.pcm_start();scenes(_session,REPETITIONS,full_source=_full_scene_source);_full_scene_source=None;gc.collect();primitives(_session,REPETITIONS);Profile(_session).run();report('transport_scenes_complete',telemetry=_session.telemetry())")
    if args.phase=='remaining':
        action="report('transport_resume',clock_hz=__import__('machine').freq(),baudrate=_session.raw.baudrate,abi=list(_session.d.abi));_session.pcm_start();micro(_session,REPETITIONS,counts=(1200,));scenes(_session,REPETITIONS,names=('A','B','C'));report('transport_resume_partial_complete',telemetry=_session.telemetry())"
    if args.phase=='finish':
        action="report('transport_resume',phase='finish',clock_hz=__import__('machine').freq(),baudrate=_session.raw.baudrate,abi=list(_session.d.abi));_session.pcm_start();calibration(REPETITIONS);scenes(_session,REPETITIONS,names=('D',),full_source=_full_scene_source);_full_scene_source=None;gc.collect();scenes(_session,REPETITIONS,names=('A','B','C'));Profile(_session).run();chunks(_session,REPETITIONS);primitives(_session,REPETITIONS);_session.verify(full=True);report('transport_complete',telemetry=_session.telemetry())"
    if args.phase=='rectangles':
        action="report('transport_resume',phase='rectangles',clock_hz=__import__('machine').freq(),baudrate=_session.raw.baudrate,abi=list(_session.d.abi));_session.pcm_start();micro(_session,REPETITIONS,counts=(256,512),layouts=('compact_rect',));_session.verify(full=False);report('transport_rectangles_complete',telemetry=_session.telemetry())"
    if args.phase=='fullblit':
        action="report('transport_resume',phase='fullblit_clean_boot',clock_hz=__import__('machine').freq(),baudrate=_session.raw.baudrate,abi=list(_session.d.abi));_session.pcm_start();scenes(_session,REPETITIONS,names=('D',),full_source=_full_scene_source);_session.fb.blit((_full_scene_source,320,240,_session.FBM.TILE4),0,0);_session.fb.flush();_session.verify(full=True);report('transport_fullblit_complete',telemetry=_session.telemetry())"
    footer='''
from framebuffer_diagnostic import Session
_session=None
gc.collect()
try:
    _session=Session(sdk=SDK_NAME,accelerated=True,viper=True)
    ACTION
finally:
    if _session is not None:_session.close()
    print('TRANSPORT_SESSION_CLOSED')
'''.replace('ACTION',action).replace('REPETITIONS',str(args.repetitions)).replace('SDK_NAME',repr(args.sdk))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(prelude+'\n'+source+footer,encoding='utf-8')
    print(args.output)
    print('workload_sha256',hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__=='__main__':main()
