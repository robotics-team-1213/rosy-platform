// LD_PRELOAD diagnostic: print a native backtrace on SIGSEGV/SIGBUS/SIGABRT.
// Installed from a constructor, i.e. before CPython's faulthandler; faulthandler chains to
// it while enabled and restores it at Py_Finalize, so crashes during C atexit/static
// destructors (after faulthandler is gone) still get a stack.
// build: gcc -shared -fPIC -O0 -o segv_bt.so segv_bt.c
#define _GNU_SOURCE
#include <execinfo.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static char altstack[1 << 16];

static void handler(int sig) {
    char buf[128];
    int n = snprintf(buf, sizeof buf, "\nNATIVE-CRASH sig=%d pid=%d tid=%ld\n", sig, getpid(),
                     (long)syscall(SYS_gettid));
    write(2, buf, n);
    void *frames[64];
    int depth = backtrace(frames, 64);
    backtrace_symbols_fd(frames, depth, 2);
    write(2, "NATIVE-CRASH end\n", 17);
    signal(sig, SIG_DFL);
    raise(sig);
}

__attribute__((constructor)) static void install(void) {
    stack_t ss = {.ss_sp = altstack, .ss_size = sizeof altstack, .ss_flags = 0};
    sigaltstack(&ss, NULL);
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = handler;
    sa.sa_flags = SA_ONSTACK | SA_RESETHAND;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    sigaction(SIGABRT, &sa, NULL);
}
