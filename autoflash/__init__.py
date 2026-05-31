import logging
import threading
import serial as pyserial
import ipaddress
import autoflash.interaction.uboot as uboot
import autoflash.interaction.openwrt as openwrt
from autoflash.interaction.serial import SerialReader

IP_NETWORK = ipaddress.IPv4Network("192.168.1.0/24")
OPENWRT_DEFAULT_LAN_IP = ipaddress.IPv4Address("192.168.1.1")
TFTP_IP = IP_NETWORK[10]


def run_autoflash(
    ramboot_file_name,
    sysupgrade_path=None,
    port="/dev/ttyUSB0",
    speed=9600,
    password="admin@huawei.com",
    ap_ip=OPENWRT_DEFAULT_LAN_IP,
    logger: logging.Logger | None = None,
    cancel_event: threading.Event | None = None,
):
    log = logger or logging.getLogger(__name__)
    debug = log.isEnabledFor(logging.DEBUG)
    with pyserial.Serial(port, speed, timeout=1) as ser:
        reader = SerialReader(ser, logger=log, cancel_event=cancel_event)

        # Ramboot
        uboot.ensure_ready(reader, password, logger=log)
        uboot.configure_ramboot(reader, TFTP_IP, ap_ip, ramboot_file_name, logger=log)
        uboot.run_ramboot(reader, logger=log)

        if not sysupgrade_path:
            return

        # Flash OpenWrt
        openwrt.wait_for_shell_ready(reader, logger=log)
        openwrt.wait_for_lan_ready(reader, logger=log)
        if ap_ip != OPENWRT_DEFAULT_LAN_IP:
            openwrt.set_lan_ip(reader, ap_ip, logger=log)
        openwrt.wait_for_pingable(reader, ap_ip, logger=log)
        openwrt.flash_openwrt(reader, ap_ip, sysupgrade_path, logger=log, debug=debug)

        # Wait for sysupgrade to finish (and the AP to come back up).
        openwrt.wait_for_shell_ready(reader, logger=log)
        # The shell prompt appears via getty long before first-boot init
        # completes. Wait for the autoconf image's uci-defaults scripts
        # and overlay setup to finish before declaring success - otherwise
        # cutting PoE here leaves the AP half-configured.
        openwrt.wait_for_first_boot_done(reader, logger=log)
