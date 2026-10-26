"""QO-100 wideband DATV slot rules used by the engine and web interface.

Frequencies are integers in kHz so slot comparisons never depend on floating
point rounding. Convert to Hz only at the Pluto MQTT boundary.
"""

SUPPORTED_SYMBOL_RATES = (125, 250, 333, 500, 1000)

ALL_SLOTS_KHZ = tuple(range(10_492_750, 10_499_251, 500))
NARROW_500_SLOTS_KHZ = tuple(range(10_492_750, 10_496_751, 500))
WIDE_1000_SLOTS_KHZ = (10_493_250, 10_494_750, 10_496_250)

DOWNLINK_TO_UPLINK_OFFSET_KHZ = 8_089_500


def allowed_slots(symbol_rate_ks):
    """Return legal downlink centre frequencies for a symbol rate."""
    if symbol_rate_ks in (125, 250, 333):
        return ALL_SLOTS_KHZ
    if symbol_rate_ks == 500:
        return NARROW_500_SLOTS_KHZ
    if symbol_rate_ks == 1000:
        return WIDE_1000_SLOTS_KHZ
    raise ValueError(f"Unsupported symbol rate: {symbol_rate_ks}")


def is_allowed(symbol_rate_ks, downlink_khz):
    """Return whether a downlink centre is legal for the symbol rate."""
    return downlink_khz in allowed_slots(symbol_rate_ks)


def revalidate_selection(symbol_rate_ks, downlink_khz):
    """Keep a legal selected frequency, otherwise clear it with ``None``."""
    if downlink_khz is None:
        return None
    return downlink_khz if is_allowed(symbol_rate_ks, downlink_khz) else None


def downlink_to_uplink_khz(downlink_khz):
    """Convert a legal QO-100 downlink display frequency to Pluto TX kHz."""
    if downlink_khz not in ALL_SLOTS_KHZ:
        raise ValueError(f"Not a recognised QO-100 slot: {downlink_khz}")
    return downlink_khz - DOWNLINK_TO_UPLINK_OFFSET_KHZ


def required_free_slots(symbol_rate_ks, downlink_khz):
    """Return the slot centres which must be free for this transmission.

    A 1000 kS wide channel occupies its selected centre and both adjacent
    500-kHz narrow slots. Narrower modes need only their selected slot free.
    """
    if not is_allowed(symbol_rate_ks, downlink_khz):
        raise ValueError(
            f"Frequency {downlink_khz} kHz is not allowed at {symbol_rate_ks} kS"
        )
    if symbol_rate_ks == 1000:
        return (downlink_khz - 500, downlink_khz, downlink_khz + 500)
    return (downlink_khz,)


def is_free(symbol_rate_ks, downlink_khz, occupied_slots_khz):
    """Return whether all slots required by a selection are unoccupied."""
    occupied = set(occupied_slots_khz)
    return occupied.isdisjoint(required_free_slots(symbol_rate_ks, downlink_khz))
