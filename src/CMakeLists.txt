idf_component_register(SRCS "main.c" "lut8.S" "lutg.S" "lutg_psk8.S" "lutg_p8s8.S" "lutg_a16.S" "lutg_a16s8.S" "lutg_a32.S"
                       REQUIRES esp_phy esp_wifi nvs_flash esp_timer esp_driver_usb_serial_jtag esp_driver_gpio)

option(DATV_TEST_COUNTER_WRAP "Seed stream counters near rollover for hardware regression tests" OFF)
if(DATV_TEST_COUNTER_WRAP)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE DATV_TEST_COUNTER_WRAP)
endif()

# Fail at link time instead of booting with data in the RF ownership bank.
# PIO PATCH: upstream used "-Wl,-T<file>". PlatformIO's builder re-adds "-T memory.ld" after the
# sorted LINKFLAGS, so a leading -T made the guard the main script and memory.ld was never read
# (link error: memory region 'iram_text_seg' not declared). Passing it as an implicit linker
# script (plain file argument) keeps the ASSERT without displacing the main script.
target_link_libraries(${COMPONENT_LIB} INTERFACE "${CMAKE_CURRENT_LIST_DIR}/rf_bank_guard.ld")
