#include "ui.h"
#include "runtime.h"
#include "diagnostics.h"
#include "wren.h"
#include <setjmp.h>
#include <stdalign.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#ifdef WD_MEMORY_DETAIL
#include <malloc.h>
#endif
#ifdef WD_JAPANESE
#include "japanese_app_source.h"
#else
#include "app_source.h"
#endif
typedef union Block Block;
union Block { struct { size_t size; Block *prev,*next; } h; max_align_t align; };
typedef struct {
    jmp_buf escape;
    Block *head;
    wd_metrics m;
    size_t budget,calls,nth;
    unsigned injection;
#ifdef WD_JAPANESE
    const char *program;
    WrenVM *active_vm;
    WrenHandle *receiver,*method;
    uint64_t session;
#endif
} Runtime;
static Runtime runtime;
#ifdef WD_JAPANESE
static uint64_t next_session;
typedef struct { WrenVM *vm; WrenHandle *receiver,*method; uint64_t session; } CallTicket;
static bool current_ticket(const CallTicket *t) {
    Runtime *r=&runtime;
    bool valid=t->vm && t->receiver && t->method && t->vm==r->active_vm && t->receiver==r->receiver && t->method==r->method && t->session==r->session;
    if (!valid) r->m.handle_rejections++;
    return valid;
}
static void clear_handles(void) { runtime.active_vm=NULL; runtime.receiver=NULL; runtime.method=NULL; }
bool wd_handles_idle(void) { return !runtime.active_vm && !runtime.receiver && !runtime.method && !runtime.program; }
#endif
enum { INIT=1,COMPILE,RUN,GC,SHUTDOWN };
static void measure(Runtime *r) {
    size_t physical=r->m.live+r->m.blocks*sizeof(Block);
    if (physical>r->m.ledger_peak) r->m.ledger_peak=physical;
    if (r->m.live>r->m.peak) r->m.peak=r->m.live;
    size_t *phase=r->m.stage==INIT?&r->m.init_peak:r->m.stage==COMPILE?&r->m.compile_peak:&r->m.run_peak;
    if (r->m.live>*phase) *phase=r->m.live;
#ifdef WD_MEMORY_DETAIL
    struct mallinfo m=mallinfo();
    if (m.arena>r->m.arena_peak) r->m.arena_peak=m.arena;
    if (m.uordblks>r->m.used_peak) r->m.used_peak=m.uordblks;
#endif
}
static void exhausted(Runtime *r,int kind) {
    r->m.oom_kind=kind; r->m.fail_stage=r->m.stage; longjmp(r->escape,1);
}
static void *tracked(void *ptr,size_t size,void *data) {
    Runtime *r=data; Block *b=ptr?(Block *)ptr-1:NULL;
    size_t old=b?b->h.size:0;
    if (!size) {
        if (b) {
            if (b->h.prev) b->h.prev->h.next=b->h.next; else r->head=b->h.next;
            if (b->h.next) b->h.next->h.prev=b->h.prev;
            r->m.live-=old; r->m.blocks--; r->m.frees++; free(b);
        }
        return NULL;
    }
    r->calls++;
    if ((r->injection==1 && r->m.stage==INIT) || (r->injection==2 && r->m.stage==COMPILE) ||
        (r->injection==3 && wd_ui_owned()) || (r->injection==4 && r->m.stage==GC) ||
        (r->injection==5 && r->calls==r->nth)) exhausted(r,3);
    if (size>r->m.largest) r->m.largest=size;
    if (size>r->budget-(r->m.live-old)) exhausted(r,1);
    bool existed=b!=NULL;
    Block *n=realloc(b,sizeof(Block)+size);
    if (!n) exhausted(r,2);
    wd_platform_check_allocation(n,sizeof(Block)+size);
    if (existed) r->m.reallocations++;
    else { r->m.allocations++; r->m.blocks++; n->h.prev=NULL; n->h.next=r->head; }
    if (n->h.prev) n->h.prev->h.next=n; else r->head=n;
    if (n->h.next) n->h.next->h.prev=n;
    n->h.size=size; r->m.live=r->m.live-old+size; measure(r);
    return n+1;
}
static void output(WrenVM *vm,const char *text) {
    Runtime *r=wrenGetUserData(vm);
    if (!strcmp(text,"こんにちは、神楽！")) r->m.utf8_outputs++;
    fputs(text,stdout);
}
static void error(WrenVM *vm,WrenErrorType type,const char *module,int line,const char *message) {
    Runtime *r=wrenGetUserData(vm); r->m.errors++;
    printf("WREN_ERROR type=%d module=%s line=%d %s\n",type,module?module:"?",line,message);
}
static void fail(WrenVM *vm,const char *message) { wrenSetSlotString(vm,0,message); wrenAbortFiber(vm,0); }
static void count(WrenVM *vm) { ((Runtime *)wrenGetUserData(vm))->m.foreign_calls++; }
static void open_window(WrenVM *vm) {
    count(vm);
    if (wrenGetSlotType(vm,1)!=WREN_TYPE_STRING) { fail(vm,"title must be a string"); return; }
    int length; const char *title=wrenGetSlotBytes(vm,1,&length);
#ifdef WD_JAPANESE
    if (length<0) { fail(vm,"negative title byte length"); return; }
    wj_title_status policy;
    bool opened=wd_ui_open_utf8(title,(size_t)length,&policy);
    if (policy!=WJ_TITLE_OK) { fail(vm,wj_title_error(policy)); return; }
    wrenSetSlotBool(vm,0,opened);
#else
    if (length>=KD_TITLE_MAX || memchr(title,0,(size_t)length)) { fail(vm,"invalid title length"); return; }
    wrenSetSlotBool(vm,0,wd_ui_open(title)); /* copies before VM can collect */
#endif
}
static void rectangle(WrenVM *vm) {
    count(vm); int a[5];
    for (int i=0;i<5;i++) {
        if (wrenGetSlotType(vm,i+1)!=WREN_TYPE_NUM) { fail(vm,"rectangle requires numbers"); return; }
        double n=wrenGetSlotDouble(vm,i+1);
        if (!isfinite(n) || n < -32768 || n>32767 || n!=(double)(int)n) { fail(vm,"rectangle requires int16 values"); return; }
        a[i]=(int)n;
    }
    wrenSetSlotBool(vm,0,wd_ui_rect(a[0],a[1],a[2],a[3],a[4]));
}
static void next_event(WrenVM *vm) { count(vm); wrenSetSlotDouble(vm,0,wd_ui_event()); }
static void present(WrenVM *vm) { count(vm); wrenSetSlotBool(vm,0,wd_ui_present()); }
#define TIMED(name,kind) static void timed_##name(WrenVM *vm) { uint64_t start=wd_platform_us(); name(vm); wd_diag_add(kind,start); }
TIMED(open_window,WD_OPEN)
TIMED(rectangle,WD_RECT)
TIMED(next_event,WD_EVENT)
TIMED(present,WD_PRESENT)
static WrenForeignMethodFn bind(WrenVM *vm,const char *module,const char *cls,bool is_static,const char *sig) {
    (void)vm;
    if (strcmp(module,"integration") || strcmp(cls,"Desktop") || !is_static) return NULL;
    if (!strcmp(sig,"open(_)")) return timed_open_window;
    if (!strcmp(sig,"rect(_,_,_,_,_)")) return timed_rectangle;
    if (!strcmp(sig,"nextEvent()")) return timed_next_event;
    if (!strcmp(sig,"present()")) return timed_present;
    return NULL;
}
static void collect(WrenVM *vm) {
    runtime.m.stage=GC; uint64_t start=wd_platform_us(); wrenCollectGarbage(vm); wd_diag_add(WD_GC,start); runtime.m.collections++;
    runtime.m.gc_live=runtime.m.live; runtime.m.stage=RUN;
}
static int execute(unsigned rounds,bool cover,bool check_errors) {
    Runtime *r=&runtime; WrenConfiguration cfg; wrenInitConfiguration(&cfg);
    cfg.reallocateFn=tracked; cfg.userData=r; cfg.writeFn=output; cfg.errorFn=error; cfg.bindForeignMethodFn=bind;
    cfg.initialHeapSize=16384; cfg.minHeapSize=8192; cfg.heapGrowthPercent=25;
    r->m.stage=INIT; uint64_t start=wd_platform_us(); WrenVM *vm=wrenNewVM(&cfg); wd_diag_add(WD_INIT,start); r->m.init_live=r->m.live;
#ifdef WD_JAPANESE
    r->active_vm=vm;
#endif
    r->m.stage=COMPILE;
#ifdef WD_JAPANESE
    const char *program=r->program;
#else
    const char *program=app_source;
#endif
    start=wd_platform_us(); bool ok=wrenInterpret(vm,"integration",program)==WREN_RESULT_SUCCESS; wd_diag_add(WD_COMPILE,start);
    r->m.compile_live=r->m.live;
    if (ok && r->injection==6) {
        wd_ui_prepare(false);
        ok=wd_ui_start() && wd_ui_open("OOM owner");
        r->m.stage=RUN;
        if (ok) (void)wrenInterpret(vm,"arena_probe","var Hold=List.filled(20000,0)\n");
        ok=false; /* probe must reach the normal whole-VM OOM boundary */
    }
    WrenHandle *receiver=NULL,*method=NULL;
#ifdef WD_JAPANESE
    CallTicket ticket={0};
#endif
    if (ok) {
        wrenEnsureSlots(vm,1); wrenGetVariable(vm,"integration","App",0);
        receiver=wrenGetSlotHandle(vm,0); method=wrenMakeCallHandle(vm,"run()");
#ifdef WD_JAPANESE
        r->receiver=receiver; r->method=method;
        ticket=(CallTicket){vm,receiver,method,r->session};
        if (check_errors) {
            CallTicket stale=ticket; stale.session--;
            ok=!current_ticket(&stale);
            stale=ticket; stale.receiver=NULL; ok=ok && !current_ticket(&stale);
            stale=ticket; stale.method=NULL; ok=ok && !current_ticket(&stale);
            stale=ticket; stale.vm=NULL; ok=ok && !current_ticket(&stale);
        }
#endif
    }
    for (unsigned i=0;ok && i<rounds;i++) {
        wd_platform_tick(); wd_ui_prepare(cover);
        if (!wd_ui_start()) { ok=false; break; }
        r->m.stage=RUN;
#ifdef WD_JAPANESE
        if (!current_ticket(&ticket)) { ok=false; break; }
#endif
        wrenEnsureSlots(vm,1); wrenSetSlotHandle(vm,0,receiver);
        start=wd_platform_us(); WrenInterpretResult status=wrenCall(vm,method); wd_diag_add(WD_CALL,start);
        ok=status==WREN_RESULT_SUCCESS && wrenGetSlotType(vm,0)==WREN_TYPE_NUM &&
            wrenGetSlotDouble(vm,0)==1406 && wd_ui_events()==4;
        if (ok && cover) {
            wd_ui_cover(false); ok=wd_ui_present();
#ifdef WD_JAPANESE
            if (ok) ok=wd_ui_move(-100,18) && wd_ui_present(); /* title partly off-screen */
            if (ok) ok=wd_ui_move(16,24) && wd_ui_present();
#endif
        }
        if (ok) r->m.completed++;
        collect(vm);
        if (ok && check_errors && i==0) {
            unsigned before=r->m.errors;
            ok=wrenInterpret(vm,"syntax","var =\n")==WREN_RESULT_COMPILE_ERROR && r->m.errors>before;
            before=r->m.errors;
            ok=ok && wrenInterpret(vm,"error","Fiber.abort(\"expected error\")\n")==WREN_RESULT_RUNTIME_ERROR && r->m.errors>before;
            /* invalid foreign args abort atomically; the window remains native-owned */
            ok=ok && wrenInterpret(vm,"badargs","import \"integration\" for Desktop\nDesktop.rect(1/0,0,2,2,1)\n")==WREN_RESULT_RUNTIME_ERROR;
            for (int j=0;ok && j<50;j++) {
                ok=wrenInterpret(vm,"repeat","{\n var tmp=List.filled(32,7)\n}\n")==WREN_RESULT_SUCCESS;
                collect(vm);
            }
        }
    }
    wd_ui_abort();
    if (wd_ui_transport()->ready && !wd_ui_present()) ok=false;
#ifdef WD_JAPANESE
    clear_handles();
    if (check_errors && receiver && current_ticket(&ticket)) ok=false;
#endif
    if (method) wrenReleaseHandle(vm,method);
    if (receiver) wrenReleaseHandle(vm,receiver);
    collect(vm); r->m.stage=SHUTDOWN; wrenFreeVM(vm);
    return ok && !r->m.live && !r->m.blocks && !r->head?0:2;
}
#ifdef WD_JAPANESE
int wd_run_script(size_t budget,unsigned rounds,bool cover,bool errors,unsigned injection,size_t nth,const char *source) {
#else
int wd_run(size_t budget,unsigned rounds,bool cover,bool errors,unsigned injection,size_t nth) {
#endif
    wd_ui_abort();
    Runtime *r=&runtime; memset(r,0,sizeof(*r)); r->budget=budget; r->injection=injection; r->nth=nth;
#ifdef WD_JAPANESE
    if (!source) { r->m.status=2; return 2; }
    r->program=source;
    if (++next_session==0) ++next_session;
    r->session=next_session;
#endif
    if (setjmp(r->escape)) {
        wd_ui_abort(); /* invalidate native owner before any fresh VM is allowed */
#ifdef WD_JAPANESE
        clear_handles(); r->program=NULL;
#endif
        while (r->head) tracked(r->head+1,0,r);
        r->m.status=(!r->m.live && !r->m.blocks && r->m.allocations==r->m.frees)?1:2;
        return r->m.status;
    }
    r->m.status=execute(rounds,cover,errors);
#ifdef WD_JAPANESE
    r->program=NULL;
#endif
    return r->m.status;
}
#ifdef WD_JAPANESE
int wd_run(size_t budget,unsigned rounds,bool cover,bool errors,unsigned injection,size_t nth) {
    return wd_run_script(budget,rounds,cover,errors,injection,nth,app_source);
}
#endif
const wd_metrics *wd_last_metrics(void) { return &runtime.m; }
