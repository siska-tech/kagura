#ifndef EXPERIMENT_H
#define EXPERIMENT_H
#include <stddef.h>
#include <stdint.h>
int experiment(size_t budget, unsigned cycles, int checks);
uint64_t experiment_time_us(void);
void experiment_tick(void);
#endif
