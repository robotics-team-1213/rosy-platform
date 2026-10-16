// Temporary native probe only: guard the literal SDK port before any traffic.
// This is not an accepted actuator runtime or protection against privileged users.
#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <spawn.h>
#include <sstream>
#include <string>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>
#include <vector>
extern char **environ;

extern "C" int rosy_omx_probe_guard_active(const char * port) {
  const char * expected = getenv("ROSY_OMX_PROBE_PORT");
  return expected && strcmp(port, expected) == 0 && geteuid() != 0;
}

static bool sole_owner(const char * path) {
  int output[2];
  if (pipe2(output, O_CLOEXEC) != 0) return false;
  posix_spawn_file_actions_t actions;
  posix_spawn_file_actions_init(&actions);
  posix_spawn_file_actions_adddup2(&actions, output[1], STDOUT_FILENO);
  posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
  posix_spawn_file_actions_addclose(&actions, output[0]);
  posix_spawn_file_actions_addclose(&actions, output[1]);
  char * argv[]{const_cast<char *>("/usr/bin/fuser"), const_cast<char *>(path), nullptr};
  std::vector<char *> env;
  for (auto item = environ; *item; ++item) {
    if (strncmp(*item, "LD_PRELOAD=", 11) != 0) env.push_back(*item);
  }
  env.push_back(nullptr);
  pid_t child;
  int error = posix_spawn(&child, argv[0], &actions, nullptr, argv, env.data());
  posix_spawn_file_actions_destroy(&actions);
  close(output[1]);
  std::string text;
  char buffer[256];
  if (!error) {
    ssize_t count;
    while ((count = read(output[0], buffer, sizeof(buffer))) > 0) {
      text.append(buffer, count);
      if (text.size() > 4096) break;
    }
  }
  close(output[0]);
  if (error) return false;
  int status;
  while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return false;
  std::istringstream parsed(text);
  std::string pid, extra;
  return WIFEXITED(status) && WEXITSTATUS(status) == 0 &&
         (parsed >> pid) && !(parsed >> extra) && pid == std::to_string(getpid());
}

static int checked(const char * path, int fd) {
  const char * expected = getenv("ROSY_OMX_PROBE_PORT");
  if (fd < 0 || !expected || strcmp(path, expected) != 0) return fd;
  struct stat info;
  const char * device_id = getenv("ROSY_OMX_PROBE_DEVICE_ID");
  if (geteuid() == 0 || fstat(fd, &info) != 0 || !S_ISCHR(info.st_mode) || !device_id ||
      std::to_string(static_cast<unsigned long long>(info.st_rdev)) != device_id) {
    close(fd); errno = EPERM; return -1;
  }
  if (ioctl(fd, TIOCEXCL) != 0) {
    int error = errno; close(fd); errno = error; return -1;
  }
  int flags = fcntl(fd, F_GETFD);
  if (flags < 0 || fcntl(fd, F_SETFD, flags | FD_CLOEXEC) < 0 || !sole_owner(path)) {
    // Do not leave our exclusivity flag on a racing opener's existing handle.
    ioctl(fd, TIOCNXCL); close(fd); errno = EBUSY; return -1;
  }
  fprintf(stderr, "OMX_EXCLUSIVE_OPEN pid=%ld fd=%d\n", static_cast<long>(getpid()), fd);
  return fd;
}

static int delegated(const char * symbol, const char * path, int flags, mode_t mode, bool has_mode) {
  using Open = int (*)(const char *, int, ...);
  auto real = reinterpret_cast<Open>(dlsym(RTLD_NEXT, symbol));
  if (!real) { errno = ENOSYS; return -1; }
  return checked(path, has_mode ? real(path, flags, mode) : real(path, flags));
}

extern "C" int open(const char * path, int flags, ...) {
  bool has_mode = (flags & O_CREAT) || ((flags & O_TMPFILE) == O_TMPFILE);
  mode_t mode = 0;
  if (has_mode) { va_list args; va_start(args, flags); mode = va_arg(args, mode_t); va_end(args); }
  return delegated("open", path, flags, mode, has_mode);
}

extern "C" int open64(const char * path, int flags, ...) {
  bool has_mode = (flags & O_CREAT) || ((flags & O_TMPFILE) == O_TMPFILE);
  mode_t mode = 0;
  if (has_mode) { va_list args; va_start(args, flags); mode = va_arg(args, mode_t); va_end(args); }
  return delegated("open64", path, flags, mode, has_mode);
}
