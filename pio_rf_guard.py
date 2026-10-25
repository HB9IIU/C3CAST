# Adds upstream's rf_bank_guard.ld to the application link only (not the bootloader).
# PlatformIO's SCons link drops the CMake INTERFACE link option, so without this the
# ASSERT (static data must stay below the RF DAC bank at 0x3fca0000) is never evaluated.
Import("env")

guard = env.subst("$PROJECT_DIR/src/rf_bank_guard.ld").replace("\\", "/")
env.Append(LINKFLAGS=[guard])
