// SPDX-License-Identifier: Apache-2.0
#include "kagura_host.h"

#include <string.h>
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/pio.h"
#include "hardware/sync.h"
#include "pico/time.h"
#include "kagura_host.pio.h"

// Transaction timing from docs/host-interface.md, with margin.
#define T_CSS_NS 250u   // /CS fall -> first SCK rise (>=200ns; PIO adds more)
#define T_CSH_NS 40u    // last SCK fall -> /CS rise (>=20ns)
#define T_CSW_NS 250u   // /CS high (>=200ns)
#define PIO_HZ_AT_DIV1 120000000.0f  // 12 PIO cycles per SCK -> 10MHz

static kh_config cfg;
static kh_stats stats;
static PIO pio = pio0;
static uint sm;
static uint prog_offset;
static uint pull_pc;            // wrap target: the SM idles stalled here
static uint8_t last_error, last_fifo_status;
static uint16_t program_buf[32];
static pio_program_t loaded_program;

static inline void wait_ns(uint32_t ns) {
    uint64_t cycles = ((uint64_t)clock_get_hz(clk_sys) * ns + 999999999u) / 1000000000u;
    busy_wait_at_least_cycles((uint32_t)cycles);
}

static bool queue_consuming(uint8_t offset) {
    return offset == KAGURA_REG_VRAM_WRITE || offset == KAGURA_REG_VRAM_READ_REQUEST || offset == KAGURA_REG_COMMAND;
}

void kh_init(const kh_config *config) {
    cfg = *config;
    memset(&stats, 0, sizeof stats);
    const pio_program_t *base = cfg.lanes == KH_QSPI ? &kagura_qspi_program : &kagura_spi_program;
    uint busy_index = cfg.lanes == KH_QSPI ? kagura_qspi_offset_busy_wait : kagura_spi_offset_busy_wait;
    // Patch the BUSY wait to the configured pin (side-set value 0 is encoded as 0).
    memcpy(program_buf, base->instructions, base->length * sizeof program_buf[0]);
    program_buf[busy_index] = (uint16_t)pio_encode_wait_gpio(false, cfg.busy_pin);
    loaded_program = *base;
    loaded_program.instructions = program_buf;
    prog_offset = pio_add_program(pio, &loaded_program);
    pull_pc = prog_offset + (cfg.lanes == KH_QSPI ? kagura_qspi_wrap_target : kagura_spi_wrap_target);
    sm = pio_claim_unused_sm(pio, true);

    gpio_init(cfg.cs_pin);
    gpio_put(cfg.cs_pin, 1);
    gpio_set_dir(cfg.cs_pin, GPIO_OUT);
    gpio_init(cfg.busy_pin);
    gpio_set_dir(cfg.busy_pin, GPIO_IN);
    gpio_init(cfg.ready_pin);
    gpio_set_dir(cfg.ready_pin, GPIO_IN);
    gpio_pull_down(cfg.ready_pin);   // unconfigured FPGA reads as not ready
    gpio_init(cfg.irq_pin);
    gpio_set_dir(cfg.irq_pin, GPIO_IN);
    gpio_pull_up(cfg.irq_pin);       // open drain; an external 3.3V pull-up is still required

    pio_sm_config c = cfg.lanes == KH_QSPI ? kagura_qspi_program_get_default_config(prog_offset)
                                           : kagura_spi_program_get_default_config(prog_offset);
    float clkdiv = (float)clock_get_hz(clk_sys) / (PIO_HZ_AT_DIV1 / (float)cfg.clkdiv);
    unsigned lanes = cfg.lanes == KH_QSPI ? 4u : 1u;
    kagura_host_sm_config(pio, sm, prog_offset, &c, cfg.io0_pin, lanes,
                          cfg.lanes == KH_QSPI ? cfg.io0_pin : cfg.io0_pin + 1, cfg.sck_pin, clkdiv);
    for (unsigned i = 0; i < (cfg.lanes == KH_QSPI ? 4u : 2u); i++) pio_gpio_init(pio, cfg.io0_pin + i);
    pio_sm_set_pins_with_mask(pio, sm, 0, 0xfu << cfg.io0_pin);
    // SPI: IO0 (MOSI) driven, IO1 (MISO) input; IO2/IO3 stay plain inputs.
    // QSPI: all four released until a transaction starts.
    uint32_t out_mask = cfg.lanes == KH_QSPI ? 0u : 1u << cfg.io0_pin;
    pio_sm_set_pindirs_with_mask(pio, sm, out_mask, (cfg.lanes == KH_QSPI ? 0xfu : 0x3u) << cfg.io0_pin);
    pio_sm_init(pio, sm, prog_offset, &c);
    pio_sm_set_enabled(pio, sm, true);
}

void kh_deinit(void) {
    pio_sm_set_enabled(pio, sm, false);
    pio_remove_program(pio, &loaded_program, prog_offset);
    pio_sm_unclaim(pio, sm);
    gpio_put(cfg.cs_pin, 1);
    // QSPI writes leave IO0..3 driven; hand all four back as plain inputs.
    for (unsigned i = 0; i < 4; i++) gpio_init(cfg.io0_pin + i);
}

const kh_config *kh_get_config(void) { return &cfg; }
kh_stats *kh_get_stats(void) { return &stats; }
uint8_t kh_last_error(void) { return last_error; }
uint8_t kh_last_fifo_status(void) { return last_fifo_status; }
bool kh_ready_pin(void) { return gpio_get(cfg.ready_pin); }
bool kh_irq_asserted(void) { return !gpio_get(cfg.irq_pin); }

kh_status kh_wait_ready(uint32_t timeout_us) {
    absolute_time_t end = make_timeout_time_us(timeout_us);
    while (!kh_ready_pin())
        if (time_reached(end)) return KH_TIMEOUT_READY;
    return KH_OK;
}

static void begin_txn(void) {
    if (cfg.lanes == KH_QSPI) {
        // The SM is stalled on `pull` while /CS is high; re-drive IO0..3.
        pio_sm_set_enabled(pio, sm, false);
        pio_sm_set_pindirs_with_mask(pio, sm, 0xfu << cfg.io0_pin, 0xfu << cfg.io0_pin);
        pio_sm_set_enabled(pio, sm, true);
    }
    gpio_put(cfg.cs_pin, 0);
    wait_ns(T_CSS_NS);
    stats.transactions++;
}

static void end_txn(void) {
    // Wait until the last byte has fully shifted out and SCK is low again.
    while (!pio_sm_is_tx_fifo_empty(pio, sm) || pio_sm_get_pc(pio, sm) != pull_pc) tight_loop_contents();
    wait_ns(T_CSH_NS);
    gpio_put(cfg.cs_pin, 1);
    wait_ns(T_CSW_NS);
}

// Clock n bytes; flags[i] bit0 = wait BUSY, bit1 = release IO after (QSPI).
static kh_status xfer(const uint8_t *tx, uint8_t *rx, const uint8_t *flags, size_t n, uint32_t timeout_us) {
    size_t sent = 0, got = 0;
    absolute_time_t end = make_timeout_time_us(timeout_us);
    while (got < n) {
        if (sent < n && !pio_sm_is_tx_fifo_full(pio, sm)) {
            uint8_t f = flags ? flags[sent] : 0;
            uint8_t b = tx ? tx[sent] : 0;
            uint32_t word = (f & 1u) ? 1u << 31 : 0;
            if (cfg.lanes == KH_QSPI) word |= ((f & 2u) ? 1u << 30 : 0) | (uint32_t)b << 22;
            else word |= (uint32_t)b << 23;
            if ((f & 1u) && gpio_get(cfg.busy_pin)) {
                // Statistics only: the PIO itself waits right before the byte.
                uint64_t t0 = time_us_64();
                stats.busy_waits++;
                while (gpio_get(cfg.busy_pin))
                    if (time_reached(end)) break;
                stats.busy_wait_us += time_us_64() - t0;
            }
            pio_sm_put(pio, sm, word);
            sent++;
        }
        if (!pio_sm_is_rx_fifo_empty(pio, sm)) {
            uint8_t b = (uint8_t)pio_sm_get(pio, sm);
            if (rx) rx[got] = b;
            got++;
        }
        if (time_reached(end)) {
            // A byte stuck behind BUSY: restart the SM so /CS can be raised;
            // the adapter discards the unfinished byte (docs: mid-byte abort).
            pio_sm_set_enabled(pio, sm, false);
            pio_sm_clear_fifos(pio, sm);
            pio_sm_restart(pio, sm);
            pio_sm_exec(pio, sm, pio_encode_jmp(pull_pc) | pio_encode_sideset(1, 0));
            pio_sm_set_enabled(pio, sm, true);
            stats.bytes_sent += got;
            return KH_TIMEOUT_BUSY;
        }
    }
    stats.bytes_sent += n;
    return KH_OK;
}

kh_status kh_write(uint8_t offset, bool inc, const uint8_t *data, size_t n) {
    if (offset > 31 || (n && !data)) return KH_BAD_ARGUMENT;
    uint8_t header = (uint8_t)((inc ? 0x40u : 0u) | offset), status;
    begin_txn();
    kh_status s = xfer(&header, &status, NULL, 1, KH_DEFAULT_TIMEOUT_US);
    if (cfg.lanes == KH_SPI) last_fifo_status = status;
    // Stream the data in chunks so the flag array stays small.
    uint8_t flags[64];
    size_t done = 0;
    while (s == KH_OK && done < n) {
        size_t chunk = n - done < sizeof flags ? n - done : sizeof flags;
        for (size_t i = 0; i < chunk; i++) {
            uint8_t target = inc ? (uint8_t)((offset + done + i) & 31u) : offset;
            flags[i] = queue_consuming(target) ? 1u : 0u;
        }
        s = xfer(data + done, NULL, flags, chunk, KH_DEFAULT_TIMEOUT_US);
        done += chunk;
    }
    end_txn();
    return s;
}

kh_status kh_read(uint8_t offset, bool inc, uint8_t *data, size_t n) {
    if (offset > 31 || n < 1 || n > 256 || !data) return KH_BAD_ARGUMENT;
    uint8_t pre[2] = {(uint8_t)(0x80u | (inc ? 0x40u : 0u) | offset), (uint8_t)(n & 0xffu)};
    uint8_t pre_flags[2] = {0, cfg.lanes == KH_QSPI ? 2u : 0u};  // QSPI turnaround after count
    uint8_t pre_rx[2], dummy;
    begin_txn();
    kh_status s = xfer(pre, pre_rx, pre_flags, 2, KH_DEFAULT_TIMEOUT_US);
    if (cfg.lanes == KH_SPI) last_fifo_status = pre_rx[0];
    if (s == KH_OK) s = xfer(NULL, &dummy, NULL, 1, KH_DEFAULT_TIMEOUT_US);
    if (s == KH_OK) s = xfer(NULL, data, NULL, n, KH_DEFAULT_TIMEOUT_US);
    end_txn();
    return s;
}

kh_status kh_write_reg(uint8_t offset, uint8_t value) { return kh_write(offset, false, &value, 1); }
kh_status kh_read_reg(uint8_t offset, uint8_t *value) { return kh_read(offset, false, value, 1); }

kh_status kh_check_errors(void) {
    uint8_t e;
    kh_status s = kh_read_reg(KAGURA_REG_ERROR_CODE, &e);
    if (s != KH_OK) return s;
    if (e) { last_error = e; return KH_DEVICE_ERROR; }
    return KH_OK;
}

kh_status kh_clear_errors(void) {
    kh_status s = kh_write_reg(KAGURA_REG_ERROR_CODE, 0xff);
    return s != KH_OK ? s : kh_write_reg(KAGURA_REG_IRQ_STATUS, KAGURA_IRQ_STATUS_ERROR);
}

kh_status kh_ext_write(uint8_t index, uint8_t value) {
    uint8_t d[2] = {index, value};
    return kh_write(KAGURA_REG_EXT_REG_INDEX, true, d, 2);
}

kh_status kh_ext_read(uint8_t index, uint8_t *value) {
    kh_status s = kh_write_reg(KAGURA_REG_EXT_REG_INDEX, index);
    return s != KH_OK ? s : kh_read_reg(KAGURA_REG_EXT_REG_DATA, value);
}

kh_status kh_audio_write(uint8_t index, uint8_t value) {
    uint8_t d[2] = {index, value};
    return kh_write(KAGURA_REG_AUDIO_REG_INDEX, true, d, 2);
}

kh_status kh_audio_read(uint8_t index, uint8_t *value) {
    kh_status s = kh_write_reg(KAGURA_REG_AUDIO_REG_INDEX, index);
    return s != KH_OK ? s : kh_read_reg(KAGURA_REG_AUDIO_REG_DATA, value);
}

kh_status kh_set_vram_addr(uint32_t addr) {
    uint8_t d[3] = {(uint8_t)addr, (uint8_t)(addr >> 8), (uint8_t)(addr >> 16)};
    return kh_write(KAGURA_REG_VRAM_ADDR_L, true, d, 3);
}

kh_status kh_set_inc(uint16_t inc) {
    uint8_t d[2] = {(uint8_t)inc, (uint8_t)(inc >> 8)};
    return kh_write(KAGURA_REG_INC_L, true, d, 2);
}

kh_status kh_wait_status(uint8_t mask, uint8_t value, uint32_t timeout_us) {
    absolute_time_t end = make_timeout_time_us(timeout_us);
    for (;;) {
        uint8_t st;
        kh_status s = kh_read_reg(KAGURA_REG_STATUS, &st);
        if (s != KH_OK) return s;
        if ((st & mask) == value) return KH_OK;
        if (time_reached(end)) return KH_TIMEOUT_STATUS;
    }
}

kh_status kh_vram_write(uint32_t addr, const uint8_t *data, size_t n) {
    kh_status s = kh_set_inc(1);
    if (s == KH_OK) s = kh_set_vram_addr(addr);
    if (s == KH_OK) s = kh_write(KAGURA_REG_VRAM_WRITE, false, data, n);
    return s != KH_OK ? s : kh_check_errors();
}

kh_status kh_vram_read(uint32_t addr, uint8_t *data, size_t n) {
    kh_status s = kh_set_inc(1);
    if (s == KH_OK) s = kh_set_vram_addr(addr);
    for (size_t i = 0; s == KH_OK && i < n; i++) {
        s = kh_write_reg(KAGURA_REG_VRAM_READ_REQUEST, 0);
        if (s == KH_OK) s = kh_wait_status(KAGURA_STATUS_READ_READY, KAGURA_STATUS_READ_READY, KH_DEFAULT_TIMEOUT_US);
        if (s == KH_OK) s = kh_read_reg(KAGURA_REG_VRAM_READ_RESULT, &data[i]);
    }
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_IRQ_STATUS, KAGURA_IRQ_STATUS_READ_DONE);
    return s != KH_OK ? s : kh_check_errors();
}

kh_status kh_fill(uint32_t addr, uint16_t length, uint8_t value) {
    uint8_t d[3] = {(uint8_t)length, (uint8_t)(length >> 8), value};
    kh_status s = kh_set_vram_addr(addr);
    if (s == KH_OK) s = kh_write(KAGURA_REG_LENGTH_L, true, d, 3);
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_COMMAND, KAGURA_CMD_FILL);
    return s != KH_OK ? s : kh_check_errors();
}

kh_status kh_fence(uint8_t tag, uint32_t timeout_us) {
    kh_status s = kh_write_reg(KAGURA_REG_FENCE_TAG, tag);
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_COMMAND, KAGURA_CMD_FENCE);
    if (s == KH_OK) s = kh_check_errors();
    absolute_time_t end = make_timeout_time_us(timeout_us);
    while (s == KH_OK) {
        uint8_t done;
        s = kh_read_reg(KAGURA_REG_DONE_TAG, &done);
        if (s == KH_OK && done == tag) break;
        if (time_reached(end)) s = KH_TIMEOUT_STATUS;
    }
    return s;
}

kh_status kh_commit(uint32_t timeout_us) {
    kh_status s = kh_write_reg(KAGURA_REG_COMMAND, KAGURA_CMD_COMMIT);
    if (s == KH_OK) s = kh_check_errors();
    return s != KH_OK ? s : kh_wait_status(KAGURA_STATUS_COMMIT_BUSY, 0, timeout_us);
}

kh_status kh_audio_commit(uint32_t timeout_us) {
    kh_status s = kh_write_reg(KAGURA_REG_COMMAND, KAGURA_CMD_AUDIO_COMMIT);
    if (s == KH_OK) s = kh_check_errors();
    absolute_time_t end = make_timeout_time_us(timeout_us);
    while (s == KH_OK) {
        uint8_t st;
        s = kh_audio_read(KAGURA_AUDIO_STATUS, &st);
        if (s == KH_OK && !(st & KAGURA_AUDIO_STATUS_APPLY_BUSY)) break;
        if (time_reached(end)) s = KH_TIMEOUT_STATUS;
    }
    return s;
}
