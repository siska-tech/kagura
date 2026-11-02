#include "runtime.h"
#include "mock_hal.h"
#include "kj_text.h"
#include "wj_title.h"
#include "japanese_app_source.h"
#define app_source ascii_app_source
#include "../../wren-desktop/src/app_source.h"
#undef app_source
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %d %s\n",__LINE__,#x); exit(2); } } while (0)
#ifndef WD_ARM_TESTS
void wd_platform_tick(void) {}
void wd_platform_check_allocation(void *p,size_t n) { (void)p;(void)n; }
uint64_t wd_platform_us(void) { return 0; }
#endif
static uint32_t reference[16];
static unsigned frames;
static bool compare;
static const char *expected_title;
static void observe(void) {
    uint8_t tile[32];
    for (unsigned t=0;t<KD_TILES;t++) {
        kd_tile4_pack_tile(&wd_ui_desktop()->fb,t,tile);
        for (unsigned i=0;i<32;i++) CHECK(tile[i]==mock_byte(t*32+i));
    }
    if (wd_ui_owned() && expected_title) CHECK(!strcmp(wd_ui_title(),expected_title));
    CHECK(frames<16);
    uint32_t crc=mock_crc(32000);
    if (compare) CHECK(reference[frames]==crc); else reference[frames]=crc;
    frames++;
}
static void balanced(void) {
    const wd_metrics *m=wd_last_metrics();
    CHECK(!m->live && !m->blocks && m->allocations==m->frees && !wd_ui_owned() && wd_handles_idle());
}
static void native_reference(const char *title,bool cover) {
    mock_reset(); wd_ui_prepare(cover); compare=false; frames=0; wd_ui_observer(observe);
    CHECK(wd_ui_start()); CHECK(wd_ui_open_utf8(title,strlen(title),NULL));
    int x=4,c=12;
    CHECK(wd_ui_rect(x,8,48,24,c) && wd_ui_present());
    for (int i=1;i<=4;i++) { CHECK(wd_ui_event()==i); x+=i; c=(c+i)%16; CHECK(wd_ui_rect(x,8,48,24,c) && wd_ui_present()); }
    CHECK(wd_ui_event()==0);
    if (cover) {
        wd_ui_cover(false); CHECK(wd_ui_present());
        CHECK(wd_ui_move(-100,18) && wd_ui_present());
        CHECK(wd_ui_move(16,24) && wd_ui_present());
    }
    wd_ui_abort(); CHECK(wd_ui_present());
}
static void script_for(char *out,size_t capacity,const char *expression,bool duplicate) {
    const char *line=strstr(app_source,"  var title = "); CHECK(line);
    const char *tail=strchr(line,'\n'); CHECK(tail);
    int n=snprintf(out,capacity,"%.*s  var title = %s%s",(int)(line-app_source),app_source,expression,tail);
    CHECK(n>0 && (size_t)n<capacity);
    if (duplicate) {
        char copy[4096]; CHECK(strlen(out)<sizeof copy); strcpy(copy,out);
        line=strstr(copy,"  title = null"); CHECK(line);
        n=snprintf(out,capacity,"%.*s  if (Desktop.open(\"duplicate\")) Fiber.abort(\"ownership failed\")\n%s",(int)(line-copy),copy,line);
        CHECK(n>0 && (size_t)n<capacity);
    }
}
static void equivalence(void) {
    static const uint32_t ascii_golden[]={0xbe72ff88,0xc91b4078,0x7017406d,0xe89d5ada,0xf07a198f,0xabb5deb8,0xbe72ff88};
    expected_title="Wren Window"; native_reference(expected_title,false);
    CHECK(frames==7 && !memcmp(reference,ascii_golden,sizeof ascii_golden));
    frames=0; compare=true; mock_reset(); CHECK(wd_run_script(262144,1,false,false,0,0,ascii_app_source)==0); balanced(); CHECK(frames==7);
    puts("ASCII_PR70_CRC_BYTE_EQUIVALENT");
    expected_title=u8"神楽 Desktop";
    for (int cover=0;cover<2;cover++) {
        native_reference(expected_title,cover!=0); unsigned count=frames;
        mock_reset(); frames=0; compare=true;
        CHECK(wd_run(262144,1,cover!=0,false,0,0)==0); balanced(); CHECK(frames==count);
        for (unsigned i=0;i<count;i++) printf("JP_CRC cover=%d frame=%u crc=%08x\n",cover,i,reference[i]);
    }
    compare=false; expected_title=NULL; wd_ui_observer(NULL);
}
static void boundary_cases(void) {
    char out[24],before[24]; memset(out,0x5a,sizeof out); memcpy(before,out,24);
    const char malformed[]={ (char)0xe3,(char)0x81 };
    CHECK(wj_title_copy(out,malformed,2)==WJ_TITLE_UTF8 && !memcmp(out,before,24));
    CHECK(wj_title_copy(out,"A\0B",3)==WJ_TITLE_NUL && !memcmp(out,before,24));
    CHECK(wj_title_copy(out,NULL,1)==WJ_TITLE_ARGUMENT);
    CHECK(wj_title_copy(out,"x",1025)==WJ_TITLE_LIMIT); /* reject length before reading */
    CHECK(wj_title_copy(out,NULL,0)==WJ_TITLE_OK && !out[0]);
    struct { const char *expression,*title; } valid[]={
        {"\"abcdefghijklmnopqrstuvw\"","abcdefghijklmnopqrstuvw"},
        {"\"abcdefghijklmnopqrstuvwx\"","abcdefghijklmnopqrstuvw"},
        {u8"\"日本語日本語日AB\"",u8"日本語日本語日AB"},
        {u8"\"日本語日本語日本\"",u8"日本語日本語日"},
        {u8"\"abcdefghijklmnopqrstuv神\"","abcdefghijklmnopqrstuv"},
        {u8"\"窓😀\"",u8"窓😀"},{"\"\"",""}
    };
    char source[4096];
    for (unsigned i=0;i<sizeof valid/sizeof valid[0];i++) {
        script_for(source,sizeof source,valid[i].expression,true); expected_title=valid[i].title;
        native_reference(expected_title,false); unsigned n=frames;
        mock_reset(); frames=0; compare=true;
        CHECK(wd_run_script(262144,1,false,false,0,0,source)==0); balanced(); CHECK(frames==n);
        printf("TITLE_CASE %u native_bytes=%zu GC-after-open CRC=equal\n",i,strlen(expected_title));
    }
    wd_ui_observer(NULL); compare=false; expected_title=NULL;
    const char *invalid[]={"123","null","true","[]", "\"A\" + String.fromByte(0) + \"B\"",
        "String.fromByte(0xc0)+String.fromByte(0xaf)","String.fromByte(0xe3)",
        "String.fromByte(0xed)+String.fromByte(0xa0)+String.fromByte(0x80)",
        "\"abcdefghijklmnopqrstuvw\"+String.fromByte(0xff)","\"A\\nB\""};
    for (unsigned i=0;i<sizeof invalid/sizeof invalid[0];i++) {
        script_for(source,sizeof source,invalid[i],false); mock_reset();
        CHECK(wd_run_script(262144,1,false,false,0,0,source)==2); balanced(); CHECK(wd_last_metrics()->errors>0);
    }
    char expression[1030]; expression[0]='"'; memset(expression+1,'A',1025); expression[1026]='"'; expression[1027]=0;
    script_for(source,sizeof source,expression,false); mock_reset();
    CHECK(wd_run_script(262144,1,false,false,0,0,source)==2); balanced();
    CHECK(!wd_ui_rect(0,0,4,4,1) && !wd_ui_move(0,0));
}
static void lifetimes(void) {
    wd_ui_observer(NULL);
    for (unsigned i=0;i<20;i++) {
        mock_reset(); CHECK(wd_run(262144,10,false,true,0,0)==0); balanced();
        CHECK(wd_last_metrics()->completed==10 && wd_last_metrics()->handle_rejections>=5);
    }
    for (unsigned phase=1;phase<=3;phase++) {
        mock_reset(); CHECK(wd_run(262144,1,false,false,phase,0)==1); balanced();
        mock_reset(); CHECK(wd_run(262144,1,false,true,0,0)==0); balanced();
    }
    for (size_t n=1;n<=8000;n+=137) { mock_reset(); int s=wd_run(262144,1,false,false,5,n); CHECK(s==0 || s==1); balanced(); }
    for (size_t cap=32768;cap<=131072;cap+=32768) {
        mock_reset(); int s=wd_run(cap,1,false,true,0,0); CHECK(s==0 || s==1); balanced(); printf("BUDGET cap=%zu status=%d peak=%zu\n",cap,s,wd_last_metrics()->peak);
    }
    mock_reset(); mock_failure_when_owned(MOCK_FENCE); CHECK(wd_run(262144,1,false,true,0,0)==2); balanced();
    mock_reset(); CHECK(wd_run(262144,1,false,true,0,0)==0); balanced();
    CHECK(wd_handles_idle());
}
int main(void) { equivalence(); boundary_cases(); lifetimes(); puts("INTEGRATION_PASS JAPANESE explicit-length strict-policy native-ownership handles GC OOM CRC clipping movement overlap"); return 0; }
