import sqlite3
import ipaddress
import threading
from . import IP_NETWORK

_lock = threading.Lock()
_con = sqlite3.connect("ips.sqlite", check_same_thread=False)
_cur = _con.cursor()

_cur.execute("""
CREATE TABLE IF NOT EXISTS ips (
    ip TEXT PRIMARY KEY NOT NULL
)
""")
_con.commit()


def get_free_ip(reserved_ips: list[ipaddress.IPv4Address]) -> ipaddress.IPv4Address:
    with _lock:
        return _get_free_ip_locked(reserved_ips)


def _get_free_ip_locked(
    reserved_ips: list[ipaddress.IPv4Address],
) -> ipaddress.IPv4Address:
    _cur.execute("SELECT ip FROM ips")

    existing_ips = list(reserved_ips)
    existing_ips.extend(ipaddress.IPv4Address(row[0]) for row in _cur.fetchall())

    for ip in IP_NETWORK.hosts():
        if ip not in existing_ips:
            _cur.execute("INSERT INTO ips (ip) VALUES (?)", (str(ip),))
            _con.commit()
            return ip

    # We're at the end, so the first ones should be free again :)
    _cur.execute("DELETE FROM ips")
    _con.commit()

    return _get_free_ip_locked(reserved_ips)
