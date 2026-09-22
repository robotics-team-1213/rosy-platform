U=rosy-core-sdtest.service
systemctl stop $U 2>/dev/null; systemctl reset-failed $U 2>/dev/null
rm -f /run/systemd/system/$U
systemctl daemon-reload
rm -rf /var/lib/rosy-sdtest /opt/rosy_sdtest /root/rosy_shutdown_home
echo "unit file: $(ls /run/systemd/system/$U /etc/systemd/system/$U 2>&1 | tr '\n' ' ')"
echo "load state: $(systemctl show -p LoadState --value $U)"
echo "leftover core: $(pgrep -f 'lib/core/core' | wc -l)"
