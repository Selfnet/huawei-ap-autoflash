import sqlite3
import ipaddress
from . import IP_NETWORK

con = sqlite3.connect("ips.sqlite")
cur = con.cursor()

# Ensure the table exists
cur.execute("""
CREATE TABLE IF NOT EXISTS ips (
    ip TEXT PRIMARY KEY NOT NULL
)
""")
con.commit()


def get_free_ip(reserved_ips: list[ipaddress.IPv4Address]) -> ipaddress.IPv4Address:
    cur.execute("SELECT ip FROM ips")

    # make a copy for us
    existing_ips = reserved_ips.copy()
    existing_ips.extend(ipaddress.IPv4Address(row[0]) for row in cur.fetchall())

    for ip in IP_NETWORK.hosts():
        if ip not in existing_ips:
            cur.execute("INSERT INTO ips (ip) VALUES (?)", (str(ip),))
            con.commit()
            return ip

    # We're at the end, so the first ones should be free again :)
    cur.execute("DELETE FROM ips")
    con.commit()

    return get_free_ip(reserved_ips)
