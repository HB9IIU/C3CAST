/* Long TX budgets. Only setup uses 64-bit arithmetic; sample loops count
 * complete maintenance blocks with a 32-bit countdown. */
#pragma once
#include <stdint.h>

static inline uint32_t tx_duration_blocks(uint32_t seconds, uint32_t baud, uint32_t symbols_per_block) {
    const uint64_t symbols = (uint64_t)seconds * baud;
    return (uint32_t)((symbols + symbols_per_block - 1u) / symbols_per_block);
}

/* Subtract in symbol units BEFORE dividing: qr may wrap before byte counter
 * qw. Both counters are unsigned and their live difference stays small. */
static inline uint32_t tx_ring_bytes(uint32_t qw, uint32_t qr, unsigned symbols_per_byte_shift) {
    return ((qw << symbols_per_byte_shift) - qr) >> symbols_per_byte_shift;
}

/* Diagnostic build only: cross a counter rollover after the first 512 bytes
 * rather than transmitting billions of symbols. Production starts at zero. */
static inline uint32_t tx_counter_seed(unsigned symbols_per_byte_shift) {
#ifdef DATV_TEST_COUNTER_WRAP
    return (UINT32_MAX >> symbols_per_byte_shift) - 511u;
#else
    (void)symbols_per_byte_shift;
    return 0;
#endif
}
