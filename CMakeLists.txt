cmake_minimum_required(VERSION 3.20)

# ============================================================================
# Amped 2 (Europe, Australia) - Static Recompilation
#
# Title ID 0x4D530041, XDK 5558, built 2003-10-03 (Microsoft Game Studios).
# Built on the xboxrecomp toolkit, cloned next to this directory.
#
# Generated code lives in src/recomp/gen/ -- regenerate it with
# tools/regen.ps1 rather than editing it by hand; put fixes in
# src/recomp_manual.c instead.
# ============================================================================

project(amped2_recomp C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Common definitions
add_compile_definitions(
    WIN32_LEAN_AND_MEAN
    NOMINMAX
)

# ── xboxrecomp toolkit ──────────────────────────────────────────
#
# Option A: xboxrecomp as a subdirectory (simplest)
#   Place xboxrecomp/ next to your game project and use a relative path.
#
# Option B: find_package (if you install xboxrecomp system-wide)
#   find_package(xboxrecomp REQUIRED)
#
# Adjust this path to point to your xboxrecomp clone:
set(XBOXRECOMP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../xboxrecomp" CACHE PATH
    "Path to the xboxrecomp toolkit root directory")

# Add xboxrecomp as a subdirectory -- this builds all 6 runtime libraries
# and provides the 'xboxrecomp' umbrella target to link against.
add_subdirectory(${XBOXRECOMP_DIR} ${CMAKE_BINARY_DIR}/xboxrecomp)

# ── Recompiled game executable ──────────────────────────────────

# Collect generated recompiled code.
# The recomp pipeline outputs files into src/recomp/gen/.
# With --split 1000, you get gen_0000.c, gen_0001.c, etc.
# CONFIGURE_DEPENDS so re-running the recompiler picks up added/removed files
# without a manual re-configure. A plain GLOB is evaluated once at configure
# time, so a newly generated file (an extra chunk, recomp_stubs_unresolved.c)
# is silently left out of the build and shows up as unresolved externals.
file(GLOB RECOMP_GEN_SOURCES CONFIGURE_DEPENDS "src/recomp/gen/*.c")

# Core game sources
set(GAME_SOURCES
    src/main.c
    src/recomp_manual.c
    src/lua_probe.c         # hand copies of generated functions, instrumented
    # Add game-specific sources here, e.g.:
    # src/asset_loader.c
    # src/custom_renderer.c
)

# The recomp pipeline also generates a dispatch header and function declarations.
# These are included by the generated .c files:
#   src/recomp/gen/recomp_funcs.h    - extern declarations for all recompiled functions
#   src/recomp/recomp_dispatch.h     - binary search dispatch table
#   src/recomp/recomp_types.h        - register model, ICALL macros, MEM helpers

add_executable(${PROJECT_NAME} WIN32
    ${GAME_SOURCES}
    ${RECOMP_GEN_SOURCES}
)

# Link against the xboxrecomp umbrella target (all 6 runtime libraries)
target_link_libraries(${PROJECT_NAME} PRIVATE xboxrecomp)

# Include paths for generated recomp headers
target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/src/recomp
    ${XBOXRECOMP_DIR}/include
)

# Windows SDK libraries needed at link time
target_link_libraries(${PROJECT_NAME} PRIVATE
    d3d11
    dxgi
    dxguid
    xinput
    winmm
    # Lets the fault handler resolve the host RIP back to the generated
    # function's symbol, i.e. to the guest function that faulted.
    dbghelp
)

# MSVC-specific: large address aware, increase section limit for big generated files
if(MSVC)
    target_link_options(${PROJECT_NAME} PRIVATE
        /LARGEADDRESSAWARE
    )
    # The generated code files can be very large. Increase object file section limit.
    target_compile_options(${PROJECT_NAME} PRIVATE /bigobj)
    # Compile the ~60 generated chunks in parallel. Capped rather than bare /MP:
    # each chunk is a whole slice of the game as one translation unit, and on a
    # 16 GB machine one compiler per core risks running out of memory.
    set(AMPED2_MP_JOBS 4 CACHE STRING "Parallel cl.exe jobs for generated code")
    target_compile_options(${PROJECT_NAME} PRIVATE /MP${AMPED2_MP_JOBS})
    # A .pdb in every config, Release included. The VEH handler in main.c turns
    # a faulting host RIP into the guest function's name (sub_XXXXXXXX) through
    # dbghelp, and without the .pdb beside the .exe it can only print addresses.
    # /OPT:REF,ICF keeps /DEBUG from switching off the linker's Release
    # optimisations.
    target_compile_options(${PROJECT_NAME} PRIVATE /Zi)
    target_link_options(${PROJECT_NAME} PRIVATE /DEBUG /OPT:REF /OPT:ICF)

    # F5 in Visual Studio: the game as the startup project, run from the
    # project root (it finds game\ and writes game\UDATA relative to it),
    # with the toolkit libraries and the generated chunks in the same
    # solution. AMPED2_DEBUG_ENV adds RECOMP_* switches to the debug
    # session, e.g. -DAMPED2_DEBUG_ENV="RECOMP_GPU_DEBUG=1".
    set_property(DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR} PROPERTY VS_STARTUP_PROJECT ${PROJECT_NAME})
    set_property(TARGET ${PROJECT_NAME} PROPERTY VS_DEBUGGER_WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")
    set(AMPED2_DEBUG_ENV "" CACHE STRING "Environment for Visual Studio debug sessions (NAME=value;...)")
    if(AMPED2_DEBUG_ENV)
        set_property(TARGET ${PROJECT_NAME} PROPERTY VS_DEBUGGER_ENVIRONMENT "${AMPED2_DEBUG_ENV}")
    endif()
endif()

# ── Game-specific additions ─────────────────────────────────────
#
# Add any game-specific libraries, loaders, or custom renderers below.
# Examples:
#
# # Custom texture loader for your game's format
# target_sources(${PROJECT_NAME} PRIVATE src/texture_loader.c)
#
# # If your game uses RenderWare, you may need a RW bridge layer
# target_sources(${PROJECT_NAME} PRIVATE src/rw_bridge.c)
#
# # Additional compile definitions for debugging
# target_compile_definitions(${PROJECT_NAME} PRIVATE
#     ENABLE_ICALL_TRACE=1
#     VERBOSE_KERNEL_LOG=1
# )
