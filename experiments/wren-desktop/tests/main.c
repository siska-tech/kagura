#include "runtime.h"
#include "mock_hal.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %s:%d %s\n",__FILE__,__LINE__,#x); exit(2); } } while (0)
#ifndef WD_ARM_TESTS
void wd_platform_tick(void) {}
void wd_platform_check_allocation(void *ptr,size_t size) { (void)ptr; (void)size; }
uint64_t wd_platform_us(void) { return 0; }
#endif
static uint32_t frames[16],reference[16];
static unsigned frame_count;
static bool compare;
static void observe(void) {
    kd_desktop *d=wd_ui_desktop(); uint8_t tile[32];
    for (unsigned t=0;t<KD_TILES;t++) {
        kd_tile4_pack_tile(&d->fb,t,tile);
        for (unsigned i=0;i<32;i++) CHECK(tile[i]==mock_byte(t*32+i));
    }
    CHECK(frame_count<16);
    frames[frame_count]=mock_crc(32000);
    if (compare) CHECK(frames[frame_count]==reference[frame_count]);
    frame_count++;
}
static void balanced(void) {
    const wd_metrics *m=wd_last_metrics();
    CHECK(m->live==0 && m->blocks==0 && m->allocations==m->frees && !wd_ui_owned());
}
static void native_reference(bool cover) {
    mock_reset(); wd_ui_prepare(cover); wd_ui_observer(observe); frame_count=0; compare=false;
    CHECK(wd_ui_start()); CHECK(wd_ui_open("Wren Window"));
    int x=4,c=12; CHECK(wd_ui_rect(x,8,48,24,c)); CHECK(wd_ui_present());
    for (int e=1;e<=4;e++) {
        CHECK(wd_ui_event()==e); x+=e; c=(c+e)%16;
        CHECK(wd_ui_rect(x,8,48,24,c)); CHECK(wd_ui_present());
    }
    CHECK(wd_ui_event()==0 && x*100+c==1406);
    if (cover) { wd_ui_cover(false); CHECK(wd_ui_present()); }
    wd_ui_abort(); CHECK(wd_ui_present());
    memcpy(reference,frames,sizeof frames);
}
static void crc_equivalence(void) {
    for (int cover=0;cover<2;cover++) {
        native_reference(cover!=0);
        unsigned count=frame_count;
        mock_reset(); frame_count=0; compare=true;
        CHECK(wd_run(262144,1,cover!=0,false,0,0)==0); balanced();
        CHECK(frame_count==count); /* includes revealing script-updated content */
        printf("CRC_EQ cover=%d frames=%u final=%08x\n",cover,count,reference[count-1]);
        for (unsigned i=0;i<count;i++) printf("CRC_REFERENCE cover=%d frame=%u crc=%08x\n",cover,i,reference[i]);
    }
    compare=false; wd_ui_observer(NULL);
}
static void failures(void) {
    wd_ui_observer(NULL);
    mock_reset(); wd_ui_prepare(false); mock_failure(MOCK_ABI);
    CHECK(!wd_ui_start() && mock_writes()==0);
    mock_reset(); wd_ui_prepare(false); mock_failure(MOCK_COMMIT); CHECK(!wd_ui_start() && !wd_ui_transport()->ready);
    for (MockFailure f=MOCK_WRITE;f<=MOCK_ERROR;f++) {
        mock_reset(); wd_ui_prepare(false); CHECK(wd_ui_start()); CHECK(wd_ui_open("Fault"));
        kd_desktop_render(wd_ui_desktop()); unsigned dirty=kd_fb_dirty_count(&wd_ui_desktop()->fb);
        CHECK(dirty>0); mock_failure(f);
        CHECK(!wd_ui_present()); CHECK(kd_fb_dirty_count(&wd_ui_desktop()->fb)==dirty);
        unsigned writes=mock_writes(); CHECK(!wd_ui_present() && mock_writes()==writes);
        mock_failure(MOCK_OK); CHECK(wd_ui_start()); CHECK(kd_fb_dirty_count(&wd_ui_desktop()->fb)==0);
    }
    mock_reset(); wd_ui_prepare(false); CHECK(wd_ui_start()); mock_reenter(true);
    CHECK(wd_ui_open("Guard")); CHECK(wd_ui_rect(-4,-4,24,24,3)); CHECK(wd_ui_present());
    CHECK(mock_reentry_rejections()>0); mock_reenter(false);
    /* Unchanged scene must send nothing, even if overdraw changed bytes transiently. */
    kd_window_invalidate_all(wd_ui_desktop(),kd_desktop_top(wd_ui_desktop()));
    unsigned writes=mock_writes(); CHECK(wd_ui_present() && mock_writes()==writes);
    CHECK(!wd_ui_rect(4,4,4,4,16));
    kd_window_invalidate_all(wd_ui_desktop(),kd_desktop_top(wd_ui_desktop()));
    CHECK(wd_ui_present() && mock_writes()==writes);
}
static void runtime_tests(void) {
    mock_reset();
    CHECK(wd_run(262144,10,false,true,0,0)==0); balanced();
    const wd_metrics *m=wd_last_metrics();
    CHECK(m->completed==10 && m->foreign_calls==161 && m->collections>=61 && m->errors>=3 && m->utf8_outputs==1); /* 160 valid + one rejected argument probe */
    for (unsigned phase=1;phase<=3;phase++) {
        mock_reset(); CHECK(wd_run(262144,1,false,false,phase,0)==1); balanced();
        mock_reset(); CHECK(wd_run(262144,1,false,false,0,0)==0); balanced();
    }
    mock_reset(); mock_failure_when_owned(MOCK_FENCE);
    CHECK(wd_run(262144,1,false,false,0,0)==2); balanced();
    CHECK(wd_ui_transport()->faulted);
    mock_reset(); CHECK(wd_run(262144,1,false,false,0,0)==0); balanced();
    for (size_t budget=1;budget<=131072;budget*=4) {
        mock_reset(); int r=wd_run(budget,1,false,false,0,0); CHECK(r==0 || r==1); balanced();
    }
    for (size_t nth=1;nth<=8000;nth+=137) {
        mock_reset(); int r=wd_run(262144,1,false,false,5,nth); CHECK(r==0 || r==1); balanced();
    }
    for (int i=0;i<20;i++) {
        mock_reset(); CHECK(wd_run(262144,10,false,true,0,0)==0); balanced();
    }
}
int main(void) { crc_equivalence(); failures(); runtime_tests(); puts("INTEGRATION_PASS single_desktop direct_ack CRC overlap clipping GC OOM recovery"); return 0; }
