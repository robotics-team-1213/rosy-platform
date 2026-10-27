"""Private ARM virt SYSTEM guest with explicit synthetic firmware properties and an owned card."""
import json
from pathlib import Path
import subprocess
import uuid

from os_system_vm import Guest, PINS


class ArmGuest(Guest):
    binary = "qemu-system-aarch64"

    def wait_boot(self):
        try:
            return super().wait_boot()
        except ValueError as error:
            path = self.directory / "guest-console.log"
            if path.is_file():
                with path.open("rb") as stream:
                    stream.seek(0, 2)
                    stream.seek(max(0, stream.tell() - 3000))
                    tail = stream.read(3000).decode(errors="replace")
                raise ValueError(str(error) + "\nguest-console.log: " + tail) from error
            raise

    def pins(self):
        common = json.loads(PINS.read_bytes())
        arm = json.loads(Path(__file__).with_name("os_system_arm_vm_inputs.json").read_bytes())
        return {**common, "debs": common["debs"] + arm["debs"], "cloud": arm["cloud"]}

    def command(self, ssh_port, seed_port):
        d = self.directory
        root = "root=/dev/vda1"
        if getattr(self, "slot", None) is not None:
            root = f"root=PARTUUID={self.root_uuid} rosy.os_layout=ab-v2 rauc.slot={self.slot}"
        return [str(self.root / "usr/bin" / self.binary), "-accel", "tcg", "-machine", "virt-8.2,gic-version=3",
            "-cpu", "cortex-a72", "-m", "2048", "-smp", "2", "-nodefaults", "-display", "none",
            "-monitor", "none", "-serial", "file:" + str(d / "guest-console.log"), "-no-reboot",
            "-L", str(self.root / "usr/share/qemu"), "-kernel", str(d / "vmlinuz"), "-initrd", str(d / "initrd"),
            "-dtb", str(d / "firmware.dtb"), "-append",
            f"{root} rw console=ttyAMA0 panic=1 ds=nocloud-net;s=http://10.0.2.2:{seed_port}/",
            "-drive", f"file={d / 'guest.qcow2'},if=virtio,format=qcow2",
            "-drive", f"file={d / 'work.raw'},if=virtio,format=raw",
            "-drive", f"file={d / 'ab-media.raw'},if=virtio,format=raw",
            "-netdev", f"user,id=network0,hostfwd=tcp:127.0.0.1:{ssh_port}-:22",
            "-device", "virtio-net-pci,netdev=network0,romfile="]

    def prepare_boot(self):
        with (self.directory / "ab-media.raw").open("xb") as stream:
            stream.truncate(12 * 1024**3)
        dtb = self.directory / "firmware.dtb"
        command = self.command(self.ssh_port, self.server.server_port)
        i = command.index("-dtb")
        del command[i:i + 2]
        command[command.index("-machine") + 1] += ",dumpdtb=" + str(dtb)
        subprocess.run(command, env=self.env, capture_output=True, check=True, timeout=60)
        tool = str(self.root / "usr/bin/fdtput")
        for name, value in (("partition", "2"), ("tryboot", "0")):
            subprocess.run([tool, "-p", "-t", "x", str(dtb), "/chosen/bootloader", name, value],
                           env=self.env, capture_output=True, check=True, timeout=30)
        subprocess.run([tool, "-t", "s", str(dtb), "/", "serial-number", "10000000abcd1234"],
                       env=self.env, capture_output=True, check=True, timeout=30)

    def restart_slot(self, root_uuid, slot, *, trial=False):
        if str(uuid.UUID(root_uuid)) != root_uuid or slot not in ("a", "b") or type(trial) is not bool:
            raise ValueError("invalid owned SYSTEM slot boot request")
        if self.run("cat /var/lib/cloud/data/instance-id").strip() != self.instance_id:
            raise ValueError("SYSTEM restart instance differs")
        self.run("sync")
        try:
            self._ssh("systemctl poweroff", timeout=20)
        except subprocess.TimeoutExpired:
            pass
        self.process.wait(timeout=90)
        self.stderr.close()
        tool, dtb = self.root / "usr/bin/fdtput", self.directory / "firmware.dtb"
        for name, value in (("partition", "2" if slot == "a" else "3"), ("tryboot", "1" if trial else "0")):
            subprocess.run([str(tool), "-p", "-t", "x", str(dtb), "/chosen/bootloader", name, value],
                           env=self.env, capture_output=True, check=True, timeout=30)
        self.root_uuid, self.slot = root_uuid, slot
        self.stderr = (self.directory / "qemu-stderr.log").open("ab")
        self.process = subprocess.Popen(self.command(self.ssh_port, self.server.server_port), env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.stderr, start_new_session=True)
        self.wait_boot()
        self.run("mkdir -p /work")
        self.run("mount -o nodev,nosuid /dev/vdb /work")
