import serial
import ipaddress
import autoflash.interaction.uboot as uboot
import autoflash.interaction.openwrt as openwrt

OPENWRT_DEFAULT_LAN_IP = ipaddress.IPv4Address("192.168.1.1")
TFTP_IP = ipaddress.IPv4Address("192.168.1.10")


def run_autoflash(
    ramboot_file_name,
    sysupgrade_path=None,
    port="/dev/ttyUSB0",
    speed=9600,
    password="admin@huawei.com",
    ap_ip=OPENWRT_DEFAULT_LAN_IP,
):
    with serial.Serial(port, speed, timeout=1) as ser:
        # Ramboot
        uboot.ensure_ready(ser, password)
        uboot.configure_ramboot(ser, TFTP_IP, ap_ip, ramboot_file_name)
        uboot.run_ramboot(ser)

        if not sysupgrade_path:
            return

        # Flash OpenWrt
        openwrt.wait_for_shell_ready(ser)
        openwrt.wait_for_lan_ready(ser)
        if ap_ip != OPENWRT_DEFAULT_LAN_IP:
            openwrt.set_lan_ip(ser, ap_ip)
        openwrt.wait_for_pingable(ser, ap_ip)
        openwrt.flash_openwrt(ser, ap_ip, sysupgrade_path)

        # Wait for sysupgrade to finish
        openwrt.wait_for_shell_ready(ser)
