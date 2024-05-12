import subprocess


def ip_responds_to_ping(ip):
    ping_cmd = [
        "ping",
        "-c",
        "1",
        "-W",
        "1",
        str(ip),
    ]

    return_code = subprocess.call(
        ping_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    return return_code == 0
