import ipaddress
import unittest
from unittest.mock import Mock, patch

import autoflash
from autoflash.interaction.serial import AbortedError


class AutoflashProgressTest(unittest.TestCase):
    def setUp(self):
        self.mock("autoflash.pyserial.Serial")
        self.mock("autoflash.SerialReader")
        self.mock("autoflash.uboot.ensure_ready", return_value="old-secret")
        self.mock("autoflash.uboot.change_password")
        self.mock("autoflash.uboot.configure_ramboot")
        self.mock("autoflash.uboot.run_ramboot")
        for name in ("wait_for_shell_ready", "wait_for_lan_ready", "set_lan_ip",
                     "wait_for_pingable", "flash_openwrt", "wait_for_first_boot_done"):
            self.mock(f"autoflash.openwrt.{name}")
        self.network = self.mock("autoflash.openwrt.read_network_info", return_value={
            "eth0": {"mac": "aa:bb:cc:dd:ee:ff"},
        })

    def mock(self, name, **kwargs):
        patcher = patch(name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def flash(self, progress=None):
        autoflash.run_autoflash(
            "ramboot.bin", "test.bin", ap_ip=ipaddress.IPv4Address("192.168.1.23"),
            password="new-secret", old_uboot_passwords=["old-secret"], progress=progress,
        )

    def test_reports_stages_password_change_and_both_network_phases(self):
        progress = Mock()
        self.flash(progress)
        events = [call.args[0] for call in progress.call_args_list]
        self.assertEqual(events[0], "opening_serial")
        self.assertIn("uboot_password_changed", events)
        self.assertIn("waiting_for_first_boot", events)
        self.assertEqual(events[-1], "first_boot_complete")
        phases = [call.kwargs["phase"] for call in progress.call_args_list if call.args == ("network",)]
        self.assertEqual(phases, ["ramboot", "installed"])
        progress.assert_any_call("configuring_ramboot", ramboot_ip="192.168.1.23", tftp_ip="192.168.1.10")

    def test_optional_network_collection_failure_does_not_fail_flash(self):
        self.network.side_effect = RuntimeError("network query unavailable")
        progress = Mock()
        with self.assertLogs("autoflash", level="WARNING"):
            self.flash(progress)
        self.assertEqual(progress.call_args.args, ("first_boot_complete",))
        self.assertEqual(sum(call.args == ("network_unavailable",) for call in progress.call_args_list), 2)

    def test_abort_during_network_collection_is_not_swallowed(self):
        self.network.side_effect = AbortedError()
        progress = Mock()
        with self.assertRaises(AbortedError):
            self.flash(progress)
        self.assertNotIn("first_boot_complete", [call.args[0] for call in progress.call_args_list])

    def test_no_extra_network_queries_for_callers_without_history(self):
        self.flash()
        self.network.assert_not_called()
