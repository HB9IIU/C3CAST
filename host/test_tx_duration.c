/* cc -O2 -Wall -Wextra -Werror host/test_tx_duration.c -o /tmp/test_tx_duration && /tmp/test_tx_duration */
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include "../firmware/main/tx_duration.h"

static void duration(uint32_t seconds, uint32_t baud, uint32_t block) {
    const uint64_t required = (uint64_t)seconds * baud;
    const uint32_t budget = tx_duration_blocks(seconds, baud, block);
    const uint64_t generated = (uint64_t)budget * block;
    assert(budget > 0 && budget < INT32_MAX);
    assert(generated >= required && generated - required < block);
    /* Cross the old 2^32-symbol ceiling without exhausting the new budget. */
    if (required > UINT32_MAX + (uint64_t)block) {
        uint32_t remaining = budget - (uint32_t)(UINT32_MAX / block);
        assert(remaining > 1);
        assert(--remaining > 0);
    }
}

static void ring_wrap(unsigned shift) {
    const uint64_t boundaries[] = {UINT64_C(1) << (32 - shift), UINT64_C(1) << 32};
    for (unsigned boundary = 0; boundary < 2; ++boundary)
        for (int delta = -64; delta <= 64; ++delta)
            for (uint32_t fill = 0; fill <= 16384; fill += 17)
                for (unsigned partial = 0; partial < (1u << shift); ++partial) {
                    const uint64_t read = boundaries[boundary] + delta;
                    const uint32_t qw = (uint32_t)(read + fill);
                    const uint32_t qr = (uint32_t)((read << shift) + partial);
                    if (!fill && partial) continue;
                    const uint32_t expected = fill - (partial != 0);
                    assert(tx_ring_bytes(qw, qr, shift) == expected);
                }
}

int main(void) {
    const uint32_t rates[] = {33000, 66000, 125000, 250000, 333000, 500000, 1000000, 1500000};
    const uint32_t seconds[] = {1, 30, 4294, 4295, 4296, 7200, 86400};
    const uint32_t blocks[] = {2048, 2050, 2051, 2056};
    for (unsigned r = 0; r < sizeof(rates)/sizeof(*rates); ++r)
        for (unsigned t = 0; t < sizeof(seconds)/sizeof(*seconds); ++t)
            for (unsigned b = 0; b < sizeof(blocks)/sizeof(*blocks); ++b)
                duration(seconds[t], rates[r], blocks[b]);
    assert(tx_duration_blocks(86400, 1000000, 2048) == 42187500);
    for (unsigned shift = 0; shift <= 2; ++shift) ring_wrap(shift);
    puts("TX duration: 24-hour budgets and byte/symbol counter rollovers passed");
    return 0;
}
