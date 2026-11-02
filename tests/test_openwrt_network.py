import unittest
from unittest.mock import Mock

from autoflash.interaction import openwrt


class NetworkInfoTest(unittest.TestCase):
    def test_collects_interface_macs_and_all_ip_addresses(self):
        output = """root@OpenWrt:/# ip -o link show; ip -o addr show
1: lo: <LOOPBACK,UP> mtu 65536 link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: eth0: <BROADCAST,UP> mtu 1500 link/ether AA:BB:CC:DD:EE:FF brd ff:ff:ff:ff:ff:ff
3: br-lan: <BROADCAST,UP> mtu 1500 link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff
4: eth0.1@eth0: <BROADCAST,UP> mtu 1500 link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff
1: lo    inet 127.0.0.1/8 scope host lo
3: br-lan    inet 192.168.1.1/24 brd 192.168.1.255 scope global br-lan
3: br-lan    inet 192.168.1.2/24 brd 192.168.1.255 scope global secondary br-lan
3: br-lan    inet6 fe80::aabb:ccff:fedd:eeff/64 scope link
NETWORK_INFO_DONE
root@OpenWrt:/#"""
        reader = Mock(buffer=output)
        interfaces = openwrt.read_network_info(reader)
        self.assertNotIn("mac", interfaces["lo"])
        self.assertEqual(interfaces["eth0"]["mac"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(interfaces["eth0.1"]["mac"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(interfaces["br-lan"]["ipv4"], ["192.168.1.1/24", "192.168.1.2/24"])
        self.assertEqual(interfaces["br-lan"]["ipv6"], ["fe80::aabb:ccff:fedd:eeff/64"])

    def test_unavailable_information_is_not_invented(self):
        reader = Mock(buffer="ip: not found\nNETWORK_INFO_DONE\nroot@OpenWrt:/#")
        self.assertEqual(openwrt.read_network_info(reader), {})

    def test_waits_for_command_completion_not_echo_or_stale_prompt(self):
        reader = Mock(buffer="")
        openwrt.read_network_info(reader)
        regex = reader.wait_for_prompt_match.call_args.args[0]
        command = reader.write.call_args.args[0].decode()
        self.assertNotRegex("root@OpenWrt:/# " + command, regex)
        self.assertNotRegex("root@OpenWrt:/#", regex)
        self.assertRegex("NETWORK_INFO_DONE\r\nroot@OpenWrt:/#", regex)
