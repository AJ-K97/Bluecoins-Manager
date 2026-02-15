# Remote Database Access

## Overview
The Bluecoins Manager database is hosted in a Docker container exposing port `5432`. It accepts connections from the local network.

## Connection Details

| Parameter | Value |
|-----------|-------|
| **Host** | `<LAN_IP_OF_THIS_MACHINE>` |
| **Port** | `5432` |
| **Database** | `bluecoins_db` |
| **User** | `bluecoins_user` |
| **Password** | `bluecoins_password` |

### Finding LAN IP
Run this command on the host machine:
```bash
ip addr | grep "inet 192"
```
*Look for an IP like `192.168.1.x`*

## Connection URL
For other services or scripts on the LAN, use:
```
postgresql+asyncpg://bluecoins_user:bluecoins_password@<LAN_IP>:5432/bluecoins_db
```

## Security Note
Default Postgres Docker images allow remote connections (`listen_addresses='*'`). Ensure your firewall (UFW) allows port 5432 if you cannot connect:
```bash
sudo ufw allow 5432/tcp
```
