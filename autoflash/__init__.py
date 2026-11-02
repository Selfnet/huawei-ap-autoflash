import logging
import threading
import serial as pyserial
import ipaddress
import autoflash.interaction.uboot as uboot
import autoflash.interaction.openwrt as openwrt
from autoflash.interaction.serial import AbortedError, SerialReader

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
    old_uboot_passwords: list[str] | None = None,
    progress=None,
):
    log = logger or logging.getLogger(__name__)
    debug = log.isEnabledFor(logging.DEBUG)

    def report(event, **details):
        if progress is not None:
            progress(event, **details)

    def record_network(reader, phase):
        if progress is None:
            return
        try:
            interfaces = openwrt.read_network_info(reader)
        except AbortedError:
            raise
        except Exception as e:
            log.warning("Could not read %s network information: %s", phase, e)
            report("network_unavailable", phase=phase, error_message=str(e))
        else:
            report("network", phase=phase, interfaces=interfaces)

    report("opening_serial")
    with pyserial.Serial(port, speed, timeout=1) as ser:
        reader = SerialReader(ser, logger=log, cancel_event=cancel_event)

        # Ramboot
        report("uboot_login")
        candidates = old_uboot_passwords or [password]
        matched_password = uboot.ensure_ready(reader, candidates, password, logger=log)
        report("uboot_ready", authenticated_password=matched_password)
        if old_uboot_passwords is not None and matched_password is not None:
            report("changing_uboot_password")
            uboot.change_password(reader, matched_password, password, logger=log)
            report("uboot_password_changed")
        report("configuring_ramboot", ramboot_ip=str(ap_ip), tftp_ip=str(TFTP_IP))
        uboot.configure_ramboot(reader, TFTP_IP, ap_ip, ramboot_file_name, logger=log)
        report("starting_ramboot")
        uboot.run_ramboot(reader, logger=log)
        report("ramboot_started")

        if not sysupgrade_path:
            return

        # Flash OpenWrt
        report("waiting_for_ramboot_shell")
        openwrt.wait_for_shell_ready(reader, logger=log)
        report("waiting_for_lan")
        openwrt.wait_for_lan_ready(reader, logger=log)
        record_network(reader, "ramboot")
        if ap_ip != OPENWRT_DEFAULT_LAN_IP:
            report("setting_flash_ip", flash_ip=str(ap_ip))
            openwrt.set_lan_ip(reader, ap_ip, logger=log)
        report("waiting_for_ping")
        openwrt.wait_for_pingable(reader, ap_ip, logger=log)
        report("copying_image")
        openwrt.flash_openwrt(
            reader, ap_ip, sysupgrade_path, logger=log, debug=debug, progress=progress
        )

        # Wait for sysupgrade to finish (and the AP to come back up).
        report("waiting_for_sysupgrade_shell")
        openwrt.wait_for_shell_ready(reader, logger=log)
        # The shell prompt appears via getty long before first-boot init
        # completes. Wait for the autoconf image's uci-defaults scripts
        # and overlay setup to finish before declaring success - otherwise
        # cutting PoE here leaves the AP half-configured.
        report("waiting_for_first_boot")
        openwrt.wait_for_first_boot_done(reader, logger=log)
        record_network(reader, "installed")
        report("first_boot_complete")
