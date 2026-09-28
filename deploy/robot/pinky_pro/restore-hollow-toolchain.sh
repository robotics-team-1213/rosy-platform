#!/bin/bash
# Restore missing/0-byte gcc, make, and cmake modules on Hub linux/arm64
# ros:jazzy-ros-base (2026-09-16). No-op when gcc, g++, make, and a
# CMakeDetermineCCompiler.cmake module are present and non-empty.
# ROSY_HOLLOW_ROOT prefixes /usr (tests). ROSY_HOLLOW_DRY_RUN=1 skips apt-get.
set -eo pipefail

ROOT="${ROSY_HOLLOW_ROOT:-}"
DRY="${ROSY_HOLLOW_DRY_RUN:-0}"

if [ -n "$ROOT" ]; then
  gcc_bin="${ROOT}/usr/bin/gcc"
  gxx_bin="${ROOT}/usr/bin/g++"
  make_bin="${ROOT}/usr/bin/make"
else
  gcc_bin="$(command -v gcc 2>/dev/null || true)"
  gxx_bin="$(command -v g++ 2>/dev/null || true)"
  make_bin="$(command -v make 2>/dev/null || true)"
fi

cmake_search="${ROOT}/usr/share/cmake-"
cmake_mod="$(ls -1 ${cmake_search}*/Modules/CMakeDetermineCCompiler.cmake 2>/dev/null | head -1 || true)"
if [ -z "$cmake_mod" ] && [ -z "$ROOT" ]; then
  cmake_mod="$(ls -1 /usr/share/cmake-*/Modules/CMakeDetermineCCompiler.cmake 2>/dev/null | head -1 || true)"
fi

need=0
reason=""
if [ -z "$gcc_bin" ] || [ ! -s "$gcc_bin" ]; then
  need=1
  reason="gcc"
fi
if [ -z "$gxx_bin" ] || [ ! -s "$gxx_bin" ]; then
  need=1
  reason="${reason:+$reason,}g++"
fi
if [ -z "$make_bin" ] || [ ! -s "$make_bin" ]; then
  need=1
  reason="${reason:+$reason,}make"
fi
if [ -z "$cmake_mod" ] || [ ! -s "$cmake_mod" ]; then
  need=1
  reason="${reason:+$reason,}cmake-modules"
fi

if [ "$need" = 0 ]; then
  echo "restore-hollow-toolchain: skip (gcc/make/cmake modules present)" >&2
  exit 0
fi

if [ "$DRY" = 1 ]; then
  echo "restore-hollow-toolchain: dry-run would reinstall gcc/g++/make/cmake-data (missing ${reason})" >&2
  exit 0
fi

apt-get install --reinstall -y --no-install-recommends \
  build-essential \
  gcc \
  g++ \
  cpp \
  make \
  cmake \
  cmake-data \
  gcc-13 \
  g++-13 \
  cpp-13 \
  binutils \
  libc6-dev
command -v gcc
command -v g++
command -v make
test -s "$(command -v make)"
cmake_mod="$(ls -1 /usr/share/cmake-*/Modules/CMakeDetermineCCompiler.cmake 2>/dev/null | head -1)"
test -n "$cmake_mod"
test -s "$cmake_mod"
gcc --version | head -1
