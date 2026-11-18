# Cross-compile RE-Amped2 for 64-bit Arm Linux (aarch64) on an x86-64 Debian
# or Ubuntu host with multiarch, e.g.:
#
#   sudo dpkg --add-architecture arm64      (plus an arm64 apt source)
#   sudo apt install gcc-aarch64-linux-gnu qemu-user qemu-user-binfmt \
#        libsdl2-dev:arm64 libgl1-mesa-dev:arm64 libepoxy-dev:arm64 \
#        libssl-dev:arm64 libavcodec-dev:arm64 libavformat-dev:arm64 \
#        libavutil-dev:arm64 libswscale-dev:arm64
#   cmake -S . -B build-arm64 -G Ninja -DCMAKE_BUILD_TYPE=Release \
#         -DCMAKE_TOOLCHAIN_FILE=cmake/toolchains/aarch64-linux-gnu.cmake
#
# The result runs on an arm64 Linux machine, or on the host through
# qemu-user (binfmt), which is how it is tested without Arm hardware.
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(CMAKE_C_COMPILER   aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)

# Multiarch: the arm64 libraries live beside the host's in /usr.
set(CMAKE_LIBRARY_ARCHITECTURE aarch64-linux-gnu)
set(CMAKE_FIND_ROOT_PATH /usr/aarch64-linux-gnu /usr/lib/aarch64-linux-gnu)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)

# pkg-config must report the arm64 .pc files, not the host's.
set(ENV{PKG_CONFIG_LIBDIR} "/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/share/pkgconfig")
