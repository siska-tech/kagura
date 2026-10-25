// SPDX-License-Identifier: Apache-2.0
// KAGURA SPI / QSPI host driver for RP2040 (docs/host-interface.md).
// Register constants come from the generated software/include/kagura_regs.h.
// Every wait has a timeout; a failed call returns a negative kh_status and
// leaves the queue-consuming operation unsent or reports where it stopped,
// so callers never resend an operation whose outcome is unknown.
#ifndef KAGURA_HOST_H
#define KAGURA_HOST_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "kagura_regs.h"

typedef enum { KH_SPI = 1, KH_QSPI = 4 } kh_lanes;

typedef enum {
    KH_OK = 0,
    KH_TIMEOUT_READY = -1,
    KH_TIMEOUT_BUSY = -2,
    KH_TIMEOUT_STATUS = -3,
    KH_DEVICE_ERROR = -4,    // ERROR_CODE became non-zero; see kh_last_error
    KH_BAD_ARGUMENT = -5,
} kh_status;

typedef struct {
    kh_lanes lanes;
    unsigned clkdiv;          // SCK = 10MHz / clkdiv (PIO at 120MHz, 12 cycles/SCK)
    unsigned io0_pin;         // IO0..IO3 on io0_pin..io0_pin+3
    unsigned sck_pin, cs_pin, busy_pin, ready_pin, irq_pin;
} kh_config;

// Counters for the M2 measurements (docs/host-interface.md, roadmap M2).
typedef struct {
    uint64_t bytes_sent;      // header, count, dummy and data bytes clocked
    uint64_t transactions;
    uint64_t busy_waits;      // queue-consuming bytes that found BUSY high
    uint64_t busy_wait_us;    // time spent before those bytes could start
} kh_stats;

#define KH_DEFAULT_TIMEOUT_US 100000u

void kh_init(const kh_config *cfg);
void kh_deinit(void);                 // release the PIO program and state machine
const kh_config *kh_get_config(void);
kh_stats *kh_get_stats(void);
uint8_t kh_last_error(void);        // ERROR_CODE seen by the last KH_DEVICE_ERROR
uint8_t kh_last_fifo_status(void);  // SPI only: FIFO_STATUS returned with the last header

bool kh_ready_pin(void);
bool kh_irq_asserted(void);         // /IRQ is open drain, active low
kh_status kh_wait_ready(uint32_t timeout_us);

// Raw transactions. inc=true advances the offset per byte (wraps at 32).
// Writes to VRAM_WRITE / VRAM_READ_REQUEST / COMMAND wait for BUSY low
// before each byte, as the adapter requires.
kh_status kh_write(uint8_t offset, bool inc, const uint8_t *data, size_t n);
kh_status kh_read(uint8_t offset, bool inc, uint8_t *data, size_t n);  // n = 1..256
kh_status kh_write_reg(uint8_t offset, uint8_t value);
kh_status kh_read_reg(uint8_t offset, uint8_t *value);

// Diagnostic-only protocol test: raise /CS halfway through either the write
// header or its first data byte. The incomplete byte must have no effect.
void kh_abort_write(bool during_header, uint8_t offset, uint8_t value);

// Register-level helpers.
kh_status kh_check_errors(void);    // KH_DEVICE_ERROR if ERROR_CODE != 0 (not cleared)
kh_status kh_clear_errors(void);    // W1C ERROR_CODE and IRQ_STATUS.ERROR
kh_status kh_ext_write(uint8_t index, uint8_t value);
kh_status kh_ext_read(uint8_t index, uint8_t *value);
kh_status kh_audio_write(uint8_t index, uint8_t value);
kh_status kh_audio_read(uint8_t index, uint8_t *value);
kh_status kh_set_vram_addr(uint32_t addr);
kh_status kh_set_inc(uint16_t inc);
kh_status kh_vram_write(uint32_t addr, const uint8_t *data, size_t n);  // INC=1
kh_status kh_vram_read(uint32_t addr, uint8_t *data, size_t n);         // READ_REQUEST per byte
kh_status kh_fill(uint32_t addr, uint16_t length, uint8_t value);
kh_status kh_copy(uint32_t src, uint32_t dst, uint16_t length);         // COMMAND COPY (CAPS PSRAM), PSRAM -> VRAM
kh_status kh_fence(uint8_t tag, uint32_t timeout_us);                   // waits DONE_TAG
kh_status kh_commit(uint32_t timeout_us);                               // waits COMMIT_BUSY=0
kh_status kh_audio_commit(uint32_t timeout_us);                         // waits APPLY_BUSY=0
kh_status kh_wait_status(uint8_t mask, uint8_t value, uint32_t timeout_us);

#endif
