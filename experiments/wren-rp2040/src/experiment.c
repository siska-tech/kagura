#include "experiment.h"
#include "wren.h"
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdalign.h>
#include "workloads.h"
#ifdef EXPERIMENT_MEMORY_DETAIL
#include <malloc.h>
#endif
enum { INIT, COMPILE, HANDLES, CALL, GC, CHECKS, SHUTDOWN, DISCARD, PHASE_COUNT };
static const char *const phase_names[] = {"init", "compile", "handles", "call", "gc", "checks", "shutdown", "discard"};
typedef struct {
    size_t start, end, peak, ledger_peak, arena_peak, used_peak, free_end, top_end;
    size_t ledger_end, used_end, arena_end;
    size_t allocs, reallocs, frees, cumulative, largest, native_live_end;
    int visited;
} Phase;

/* The budget covers requested VM bytes, not malloc headers/fragmentation.
 * Own every allocation separately so an interrupted VM can be discarded.
 * Wren does NOT propagate allocator NULL as a recoverable script error.
 * No foreign objects/finalizers/resources are allowed in this experiment. */
typedef union Block Block;
union Block {
    struct { size_t size; Block *prev, *next; } h;
    max_align_t alignment;
};
typedef struct {
    jmp_buf escape;
    Block *head;
    size_t live, peak, physical, physical_peak, blocks, allocs, reallocs, frees;
    size_t largest, budget, init, compiled, after_gc, oom_request, foreign_calls;
    size_t gc_count;
    size_t init_allocs, compile_allocs, run_allocs, run_reallocs;
    size_t init_peak, init_physical_peak, largest_success;
    uint64_t elapsed, gc_us, compile_us;
    unsigned errors, output_bytes;
    int quiet, oom, failed;
    const char *stage;
    const char *oom_kind;
    Phase phases[PHASE_COUNT];
    int phase;
    size_t cumulative, growth_bytes, moved_reallocs, native_live;
    size_t peak_blocks, peak_phase, peak_ledger_at_live;
    size_t executed;
    size_t peak_usable, peak_malloc_used, peak_arena;
} Context;
static Context context; /* outside setjmp frame; no indeterminate automatic state */

static void snapshot(Context *c) {
    Phase *p = &c->phases[c->phase];
    p->end = c->live;
    p->ledger_end = c->physical;
    if (c->live > p->peak) p->peak = c->live;
    if (c->physical > p->ledger_peak) p->ledger_peak = c->physical;
#ifdef EXPERIMENT_MEMORY_DETAIL
    struct mallinfo m = mallinfo();
    if (m.arena > p->arena_peak) p->arena_peak = m.arena;
    if (m.uordblks > p->used_peak) p->used_peak = m.uordblks;
    p->free_end = m.fordblks; p->top_end = m.keepcost;
    p->used_end = m.uordblks; p->arena_end = m.arena;
    p->native_live_end = c->native_live;
#endif
}
static void phase(Context *c, int id) {
    snapshot(c); c->phase = id; c->stage = phase_names[id];
    Phase *p = &c->phases[id];
    if (!p->visited) { p->visited = 1; p->start = c->live; }
    snapshot(c);
}

static void *tracked(void *ptr, size_t size, void *data) {
    Context *c = data;
    Block *b = ptr ? (Block *)ptr - 1 : NULL;
    size_t old = b ? b->h.size : 0;
    Phase *p = &c->phases[c->phase];
    if (!size) {
        if (b) {
            if (b->h.prev) b->h.prev->h.next = b->h.next; else c->head = b->h.next;
            if (b->h.next) b->h.next->h.prev = b->h.prev;
            c->live -= old; c->physical -= old + sizeof(Block);
            c->blocks--; c->frees++; p->frees++;
#ifdef EXPERIMENT_MEMORY_DETAIL
            c->native_live -= malloc_usable_size(b);
#endif
            free(b); snapshot(c);
        }
        return NULL;
    }
    if (size > c->largest) c->largest = size;
    if (size > c->budget - (c->live - old)) {
        c->oom = 1; c->oom_kind = "budget"; c->oom_request = size; longjmp(c->escape, 1);
    }
    bool existed = b != NULL;
    uintptr_t old_address = (uintptr_t)b;
#ifdef EXPERIMENT_MEMORY_DETAIL
    size_t old_native = b ? malloc_usable_size(b) : 0;
#endif
    Block *n = realloc(b, sizeof(Block) + size);
    if (!n) { snapshot(c); c->oom = 1; c->oom_kind = "malloc"; c->oom_request = size; longjmp(c->escape, 1); }
#ifdef EXPERIMENT_MEMORY_DETAIL
    c->native_live = c->native_live - old_native + malloc_usable_size(n);
#endif
    if (existed && (uintptr_t)n != old_address) c->moved_reallocs++;
    c->cumulative += size; p->cumulative += size;
    if (size > old) c->growth_bytes += size - old;
    if (size > p->largest) p->largest = size;
    if (size > c->largest_success) c->largest_success = size;
    if (existed) { c->reallocs++; p->reallocs++; }
    else { c->allocs++; p->allocs++; c->blocks++; n->h.prev = NULL; n->h.next = c->head; }
    if (n->h.prev) n->h.prev->h.next = n; else c->head = n;
    if (n->h.next) n->h.next->h.prev = n;
    n->h.size = size;
    c->live = c->live - old + size;
    c->physical = c->live + c->blocks * sizeof(Block);
    if (c->live > c->peak) {
        c->peak = c->live; c->peak_blocks = c->blocks;
        c->peak_phase = (size_t)c->phase; c->peak_ledger_at_live = c->physical;
#ifdef EXPERIMENT_MEMORY_DETAIL
        struct mallinfo m = mallinfo();
        c->peak_usable = c->native_live; c->peak_malloc_used = m.uordblks; c->peak_arena = m.arena;
#endif
    }
    if (c->physical > c->physical_peak) c->physical_peak = c->physical;
    snapshot(c);
    return n + 1;
}
static void discard(Context *c) {
    while (c->head) tracked(c->head + 1, 0, c);
}
static void write_output(WrenVM *vm, const char *s) {
    Context *c = wrenGetUserData(vm);
    c->output_bytes += (unsigned)strlen(s);
    if (!c->quiet) fputs(s, stdout);
}
static void error_output(WrenVM *vm, WrenErrorType type, const char *module, int line, const char *msg) {
    Context *c = wrenGetUserData(vm);
    c->errors++;
    printf("ERROR %d %s:%d %s\n", type, module ? module : "?", line, msg);
}
static void foreign_add(WrenVM *vm) {
    Context *c = wrenGetUserData(vm);
    c->foreign_calls++;
    wrenSetSlotDouble(vm, 0, wrenGetSlotDouble(vm, 1) + 1);
}
static WrenForeignMethodFn bind(WrenVM *vm, const char *module, const char *class_name, bool is_static, const char *signature) {
    (void)vm;
    return !strcmp(module, "bench") && !strcmp(class_name, "Native") && is_static && !strcmp(signature, "add(_)") ? foreign_add : NULL;
}
static WrenVM *new_vm(Context *c) {
    WrenConfiguration cfg;
    wrenInitConfiguration(&cfg);
    cfg.reallocateFn = tracked; cfg.userData = c;
    cfg.writeFn = write_output; cfg.errorFn = error_output; cfg.bindForeignMethodFn = bind;
    cfg.initialHeapSize = 16 * 1024; cfg.minHeapSize = 8 * 1024; cfg.heapGrowthPercent = 25;
    return wrenNewVM(&cfg);
}
static void collect(Context *c, WrenVM *vm) {
    int previous = c->phase;
    phase(c, GC);
    volatile uint64_t t = experiment_time_us();
    wrenCollectGarbage(vm);
    c->gc_us += experiment_time_us() - t;
    c->gc_count++;
    phase(c, previous);
}
static int run_body(Context *c, const Workload *w, int checks) {
    phase(c, INIT);
    WrenVM *vm = new_vm(c);
    c->init = c->live;
    c->init_peak = c->peak; c->init_physical_peak = c->physical_peak;
    c->init_allocs = c->allocs;
    phase(c, COMPILE);
    volatile uint64_t t = experiment_time_us();
    if (wrenInterpret(vm, "bench", w->source) != WREN_RESULT_SUCCESS) c->failed = 1;
    c->compile_us = experiment_time_us() - t;
    c->compiled = c->live;
    c->compile_allocs = c->allocs - c->init_allocs;
    if (!c->failed) {
        phase(c, HANDLES);
        wrenEnsureSlots(vm, 1);
        wrenGetVariable(vm, "bench", "Bench", 0);
        WrenHandle *receiver = wrenGetSlotHandle(vm, 0);
        WrenHandle *method = wrenMakeCallHandle(vm, "run()");
        phase(c, CALL);
        /* 2 warm-ups + 8 measured calls; restore receiver slot every time. */
        for (int i = -2; i < 8; i++) {
            experiment_tick();
            wrenEnsureSlots(vm, 1);
            wrenSetSlotHandle(vm, 0, receiver);
            c->quiet = 1;
            size_t a0 = c->allocs, r0 = c->reallocs;
            t = experiment_time_us();
            WrenInterpretResult r = wrenCall(vm, method);
            c->executed = c->live;
            if (i >= 0) {
                c->elapsed += experiment_time_us() - t;
                c->run_allocs += c->allocs - a0;
                c->run_reallocs += c->reallocs - r0;
            }
            if (r != WREN_RESULT_SUCCESS || wrenGetSlotType(vm, 0) != WREN_TYPE_NUM || wrenGetSlotDouble(vm, 0) != w->expected) c->failed = 1;
            collect(c, vm);
        }
        c->quiet = 0;
        wrenReleaseHandle(vm, method); wrenReleaseHandle(vm, receiver);
        if (checks) {
            phase(c, CHECKS);
            /* Same-module repeated interpretation, not callback recompilation. */
            for (int i = 0; i < 50; i++) {
                if (wrenInterpret(vm, "repeat", "{\n var scratch = List.filled(32, 7)\n}\n") != WREN_RESULT_SUCCESS) c->failed = 1;
                collect(c, vm);
            }
            unsigned before = c->errors;
            if (wrenInterpret(vm, "badcompile", "var =\n") != WREN_RESULT_COMPILE_ERROR || c->errors == before) c->failed = 1;
            before = c->errors;
            if (wrenInterpret(vm, "badruntime", "Fiber.abort(\"expected failure\")\n") != WREN_RESULT_RUNTIME_ERROR || c->errors == before) c->failed = 1;
            /* VM remains usable after ordinary errors. */
            if (wrenInterpret(vm, "recover", "var ok = 42\n") != WREN_RESULT_SUCCESS) c->failed = 1;
        }
    }
    collect(c, vm); c->after_gc = c->live;
    phase(c, SHUTDOWN); wrenFreeVM(vm); snapshot(c);
    if (c->live || c->head || c->physical || c->native_live) c->failed = 1;
    return c->failed ? 2 : 0;
}
static int run(Context *c, const Workload *w, int checks) {
    if (setjmp(c->escape)) {
        const char *failed_stage = c->stage;
        phase(c, DISCARD); discard(c); c->stage = failed_stage; return 1;
    }
    return run_body(c, w, checks);
}
int experiment_named(size_t budget, unsigned cycles, int checks, const char *name) {
    int status = 0;
    for (unsigned cycle = 0; cycle < cycles; cycle++) {
        for (size_t i = 0; i < sizeof(workloads) / sizeof(workloads[0]) + 1; i++) {
            const Workload *w = i < sizeof(workloads)/sizeof(workloads[0]) ? &workloads[i] : &gui_workload;
            if (name ? strcmp(name, w->name) != 0 : w == &gui_workload) continue;
            Context *c = &context;
            memset(c, 0, sizeof(*c)); c->budget = budget;
            int r = run(c, w, checks && (i == 0 || name));
            if (r > status) status = r;
            printf("RESULT name=%s cycle=%u budget=%zu status=%s stage=%s init=%zu compiled=%zu after_gc=%zu shutdown=%zu peak=%zu physical_peak=%zu allocs=%zu reallocs=%zu frees=%zu largest=%zu oom_request=%zu compile_us=%llu run_us=%llu samples=8 explicit_gc_us=%llu explicit_gc_count=%zu foreign_calls=%zu header=%zu init_allocs=%zu compile_allocs=%zu run_allocs=%zu run_reallocs=%zu init_peak=%zu init_physical_peak=%zu largest_success=%zu oom_kind=%s\n",
                w->name, cycle, budget, r == 1 ? "OOM_DISCARDED" : r == 2 ? "FAIL" : "PASS", c->stage,
                c->init, c->compiled, c->after_gc, c->live, c->peak, c->physical_peak, c->allocs, c->reallocs, c->frees, c->largest, c->oom_request,
                (unsigned long long)c->compile_us, (unsigned long long)c->elapsed, (unsigned long long)c->gc_us, c->gc_count, c->foreign_calls, sizeof(Block), c->init_allocs, c->compile_allocs, c->run_allocs, c->run_reallocs, c->init_peak, c->init_physical_peak, c->largest_success, c->oom_kind ? c->oom_kind : "none");
            printf("AUDIT name=%s cumulative=%zu growth=%zu moved_reallocs=%zu peak_phase=%s peak_blocks=%zu ledger_at_peak=%zu native_live=%zu executed=%zu peak_usable=%zu peak_malloc_used=%zu peak_arena=%zu\n",
                   w->name, c->cumulative, c->growth_bytes, c->moved_reallocs, phase_names[c->peak_phase], c->peak_blocks, c->peak_ledger_at_live, c->native_live, c->executed, c->peak_usable, c->peak_malloc_used, c->peak_arena);
            for (int j = 0; j < PHASE_COUNT; j++) {
                Phase *p = &c->phases[j];
                if (!p->visited) continue;
                printf("PHASE name=%s phase=%s start=%zu end=%zu peak=%zu ledger_peak=%zu arena_peak=%zu used_peak=%zu free_end=%zu top_end=%zu native_live_end=%zu allocs=%zu reallocs=%zu frees=%zu cumulative=%zu largest=%zu ledger_end=%zu used_end=%zu arena_end=%zu\n",
                       w->name, phase_names[j], p->start, p->end, p->peak, p->ledger_peak, p->arena_peak, p->used_peak,
                       p->free_end, p->top_end, p->native_live_end, p->allocs, p->reallocs, p->frees, p->cumulative, p->largest, p->ledger_end, p->used_end, p->arena_end);
            }
            if (c->head) discard(c);
        }
    }
    return status;
}
int experiment(size_t budget, unsigned cycles, int checks) {
    return experiment_named(budget, cycles, checks, NULL);
}
