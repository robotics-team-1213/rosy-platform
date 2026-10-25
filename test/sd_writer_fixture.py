"""Native fake executable for the file-only SD writer tests."""
import os
import shlex


def make_writer(tmp_path):
    marker = tmp_path / "writer-called.txt"
    writer_args = tmp_path / "writer-args.txt"
    fake_writer = tmp_path / "fake-writer.cmd"
    fake_writer.write_text(
        f'@echo off\n> "{marker}" echo called\n> "{writer_args}" echo %*\nexit /b 0\n',
        encoding="utf-8",
    )
    if os.name != "nt":
        fake_writer = tmp_path / "fake-writer"
        fake_writer.write_text(
            "#!/bin/sh\n" + f"printf 'called\\n' > {shlex.quote(str(marker))}\n"
            + f"printf '%s ' \"$@\" > {shlex.quote(str(writer_args))}\nexit 0\n", encoding="utf-8")
        fake_writer.chmod(0o700)
    return fake_writer, marker, writer_args
