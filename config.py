import ipaddress

tftp_ip = ipaddress.IPv4Address("192.168.1.10")

openwrt_images_path = ""

# For this prefix, there are two images: <prefix>-initramfs-kernel.bin and <prefix>-squashfs-sysupgrade.bin
openwrt_images_prefix = "openwrt-ath79-generic-huawei_ap5030dn-"
