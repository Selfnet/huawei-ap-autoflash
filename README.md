# Huawei APXXXXDN Autoflasher

Automated flashing tool for Huawei AP access points with OpenWrt firmware. This tool automates the process of flashing OpenWrt onto Huawei AP devices via serial connection, supporting both ramboot and full sysupgrade installations.

## Features

- Automated U-Boot interaction for rambooting OpenWrt
- Full sysupgrade flashing support
- Automated configuration mode with pre-configured images
- Label printing support for WiFi credentials and login information
- IP address management to prevent conflicts
- Support for flashing multiple APs sequentially

## Requirements

### Hardware
- Huawei AP access point (APXXXXDN series)
- USB-to-Serial adapter (FTDI or similar)
- TFTP server running on the host machine
- Network connection between host and AP
- (Optional) Brother QL-series label printer for automatic label printing

### Software
- Python 3.x
- TFTP server configured and running
- Serial port access permissions

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd huawei-apxxxxdn-autoflash
```

2. Install Python dependencies (managed by [uv](https://docs.astral.sh/uv/)):
```bash
uv sync
```

System packages required for PyGObject / pycairo (Debian/Ubuntu/Raspbian):
```bash
sudo apt install libcairo2-dev libgirepository1.0-dev libgirepository-2.0-dev pkg-config meson
```

3. Ensure your TFTP server is running and configured to serve files from the appropriate directory.

## Usage

### Basic Autoflash Mode

Flash a single AP with specified firmware images:

```bash
python autoflash.py <ramboot-filename> [options]
```

#### Arguments

- `ramboot_file_name`: Ramboot filename (must be in TFTP server directory)
  - Example: `openwrt-ath79-generic-huawei_apXXXXdn-initramfs-kernel.bin`

#### Options

- `--sysupgrade-path PATH`: Path to sysupgrade image file
  - Example: `openwrt-ath79-generic-huawei_apXXXXdn-squashfs-sysupgrade.bin`
  - If not provided, only ramboot will be performed
- `--port PORT`: Serial port device (default: `/dev/ttyUSB0`)
- `--speed BAUD`: Serial baudrate (default: `9600`)
- `-p, --password PASS`: U-Boot bootloader password (default: `admin@huawei.com`)
- `--ap-ip IP`: IP address to assign to the AP (default: `192.168.1.1`)
- `-v, --verbose`: Enable verbose logging
- `-d, --debug`: Enable debug logging with serial output

#### Example

```bash
# Ramboot only
python autoflash.py ramboot.bin

# Full flash with sysupgrade
python autoflash.py ramboot.bin --sysupgrade-path /path/to/sysupgrade.bin

# Custom serial port and password
python autoflash.py ramboot.bin --port /dev/ttyUSB1 -p mypassword --sysupgrade-path sysupgrade.bin
```

### Automated Configuration Mode

Flash APs using pre-configured images with metadata and optional label printing:

```bash
python flash_autoconf.py -i <images-directory> [options]
```

This mode:
1. Randomly selects a `.json` metadata file from the images directory
2. Uses the corresponding `.bin` sysupgrade file
3. Optionally prints WiFi and login labels
4. Automatically assigns a free IP address
5. Performs the complete flash process
6. Removes processed files after successful flash

#### Arguments

- `-i, --images-dir PATH`: Directory containing `.json` metadata files and corresponding `.bin` sysupgrade images (required)

#### Options

- `--port PORT`: Serial port device (default: `/dev/ttyUSB0`)
- `-s, --speed BAUD`: Serial baudrate (default: `9600`)
- `-p, --password PASS`: U-Boot bootloader password (default: `dasuboot`)
- `-l, --labelprinter HOST`: Hostname/IP of Brother QL label printer (if not set, no labels printed)
- `-d, --debug`: Enable debug logging with serial output

#### Metadata File Format

The metadata `.json` files should contain:
```json
{
  "ssid": "WiFi-Network-Name",
  "wifi_password": "wifi-password",
  "root_password": "root-password"
}
```

#### Example

```bash
# Flash with automatic configuration
python flash_autoconf.py -i /path/to/images

# With label printer
python flash_autoconf.py -i /path/to/images -l printer.local

# Custom serial port and bootloader password
python flash_autoconf.py -i /path/to/images --port /dev/ttyUSB1 -p mypassword
```

### Using Justfile

If you have [just](https://github.com/casey/just) installed, you can use the provided shortcuts:

```bash
# Basic autoflash
just autoflash ramboot.bin --sysupgrade-path sysupgrade.bin

# Automated configuration
just flash_autoconf -i /path/to/images
```

## Exact Requirements for Autoflash to Work

### Physical Connections

**REQUIRED:**
1. **Serial Connection**: USB-to-Serial adapter connected from host computer to AP's serial console
   - Default device: `/dev/ttyUSB0` (configurable with `--port`)
   - Default baudrate: `9600` (configurable with `--speed`)

2. **Network Connection**: Ethernet cable from AP to host computer's network
   - Must be on same Layer 2 network (same switch/broadcast domain)
   - AP will obtain connectivity through its LAN port

### Network Interface Configuration

**REQUIRED on Host Computer:**

The host computer MUST have a network interface configured with these specific IPs on the `192.168.1.0/24` network:

1. **TFTP Server IP: `192.168.1.10`**
   - This IP MUST be configured on the host's network interface
   - The AP will download the ramboot image from this IP via TFTP
   - Configure with: `sudo ip addr add 192.168.1.10/24 dev <interface>`

2. **Host must be able to reach the AP's IP**
   - Default AP IP: `192.168.1.1` (configurable with `--ap-ip`)
   - Host must be able to ping this IP
   - Host must be able to SCP to this IP (for sysupgrade phase)

**Example Network Configuration:**
```bash
# Configure your network interface (replace eth0 with your interface name)
sudo ip addr add 192.168.1.10/24 dev eth0
sudo ip link set eth0 up
```

### TFTP Server Requirements

**REQUIRED:**
1. TFTP server must be running on the host
2. TFTP server must listen on IP `192.168.1.10`
3. The ramboot image file must be in the TFTP server's root directory
4. TFTP server must be accessible (check firewall allows UDP port 69)

**Example TFTP Server Setup (tftpd-hpa):**
```bash
# Configure /etc/default/tftpd-hpa
TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/srv/tftp"
TFTP_ADDRESS="192.168.1.10:69"
TFTP_OPTIONS="--secure"

# Place ramboot image
sudo cp ramboot.bin /srv/tftp/

# Start service
sudo systemctl restart tftpd-hpa
sudo systemctl enable tftpd-hpa
```

**Example TFTP Server Setup (dnsmasq):**
```bash
sudo dnsmasq --no-daemon --listen-address=0.0.0.0 --port=0 --enable-tftp=eno1 --tftp-root="$(pwd)" --user=root --group=root
```

### Process Flow and Network Requirements

**Phase 1 - U-Boot Ramboot:**
1. Script connects via serial (USB-to-Serial adapter)
2. Script interrupts boot sequence and enters U-Boot
3. Script authenticates with bootloader password
4. Script configures U-Boot environment:
   - `serverip` = `192.168.1.10` (TFTP server)
   - `ipaddr` = AP IP (e.g., `192.168.1.1`)
   - `rambootfile` = filename
5. Script waits 5 seconds for AP's LAN interface to be ready
6. Script executes `run ramboot` command
7. **AP downloads ramboot image via TFTP from `192.168.1.10`** (requires TFTP server)
8. AP boots into OpenWrt ramboot image

**Phase 2 - OpenWrt Sysupgrade (if `--sysupgrade-path` provided):**
1. Script waits for OpenWrt shell to be ready via serial
2. Script waits for `br-lan` network interface to be ready on AP
3. If custom IP specified, script changes AP's LAN IP using UCI
4. **Script pings AP from host** (requires host to have route to AP IP)
5. **Script copies sysupgrade image via SCP to `root@<AP-IP>:/tmp`** (requires SSH/SCP and network connectivity)
6. Script executes `sysupgrade -n /tmp/<image>` on AP via serial
7. Script waits for reboot and OpenWrt shell to be ready again

### Complete Checklist

Before running autoflash, verify:

- [ ] USB-to-Serial adapter connected to host and AP serial console
- [ ] Serial device exists (check with `ls /dev/ttyUSB*`)
- [ ] User has serial port permissions (`sudo usermod -a -G dialout $USER`)
- [ ] Ethernet cable connected between AP and host's network
- [ ] Host has IP `192.168.1.10/24` configured on network interface
- [ ] TFTP server running and listening on `192.168.1.10:69`
- [ ] Ramboot image file is in TFTP server root directory (filename only, no path)
- [ ] Firewall allows TFTP (UDP port 69)
- [ ] Firewall allows SSH/SCP (TCP port 22) to AP IP
- [ ] Host can route to AP IP (e.g., `192.168.1.1`)
- [ ] AP is powered on or ready to be powered on
- [ ] Correct bootloader password known

### IP Address Allocation

**Default Network: `192.168.1.0/24`**

- `192.168.1.10` - **TFTP Server** (host computer, REQUIRED)
- `192.168.1.1` - **Default AP IP** (configurable with `--ap-ip`)
- `192.168.1.2-192.168.1.254` - Available for custom AP IPs

In `flash_autoconf.py` mode, the script automatically assigns free IPs from the `192.168.1.0/24` network, tracking used IPs in `ips.sqlite` database.

### Debug Mode
Run with `-d` or `--debug` to see full serial output and diagnose issues:
```bash
python autoflash.py ramboot.bin --debug
```
