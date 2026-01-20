# Bambu Lab MQTT Integration

This guide explains how to set up automatic filament tracking for Bambu Lab 3D printers using MQTT.

## Overview

The Bambu Lab MQTT integration allows Spoolman to automatically track filament usage in real-time by connecting directly to your Bambu Lab printer's MQTT broker. When you print with your AMS (Automatic Material System), Spoolman will automatically update the remaining weight of the corresponding spools.

## Features

- **Real-time Updates**: Spool weights update automatically as you print
- **Wireless Connection**: Connects to your printer over WiFi/Ethernet
- **Multi-Spool Support**: Track up to 4 spools per AMS unit
- **Automatic Reconnection**: Handles network disconnections gracefully
- **Secure Connection**: Uses TLS/SSL encryption

## Prerequisites

1. **Bambu Lab Printer** with MQTT enabled (X1 Carbon, P1P, P1S, A1, etc.)
2. **LAN-Only Mode** enabled on your printer
3. **Spoolman** running on the same network as your printer
4. **AMS** (Automatic Material System) installed (optional but recommended)

## Step 1: Enable LAN-Only Mode on Your Printer

1. On your printer's touchscreen, go to **Settings**
2. Navigate to **Network** > **LAN-Only Mode**
3. Enable **LAN-Only Mode**
4. Note down the **Access Code** (8-digit password) - you'll need this later

## Step 2: Find Your Printer's Serial Number

1. On your printer's touchscreen, go to **Settings**
2. Navigate to **Device** or **About**
3. Find and note down the **Serial Number** (e.g., `01S00A123456789`)

## Step 3: Find Your Printer's IP Address

You can find your printer's IP address in one of these ways:

- Check your printer's touchscreen under **Settings** > **Network**
- Check your router's DHCP client list
- Use a network scanning tool like `nmap` or `Angry IP Scanner`

## Step 4: Create Spools in Spoolman

Before mapping AMS slots to spools, you need to create the spools in Spoolman:

1. Open the Spoolman web interface
2. Create filament types if they don't exist
3. Create spools for each AMS slot you want to track
4. Note down the **Spool ID** for each spool (visible in the URL or spool details)

## Step 5: Configure Spoolman Environment Variables

Add these settings to your `.env` file or Docker environment:

```bash
# Enable MQTT client
SPOOLMAN_MQTT_ENABLED=TRUE

# Your printer's IP address
SPOOLMAN_MQTT_HOST=192.168.1.100

# MQTT port (8883 is the default for Bambu Lab)
SPOOLMAN_MQTT_PORT=8883

# MQTT username (always "bblp" for Bambu Lab)
SPOOLMAN_MQTT_USERNAME=bblp

# LAN-Only Mode access code from Step 1
SPOOLMAN_MQTT_PASSWORD=12345678

# Your printer's serial number from Step 2
SPOOLMAN_MQTT_DEVICE_SERIAL=01S00A123456789

# Enable TLS/SSL (required for Bambu Lab)
SPOOLMAN_MQTT_TLS=TRUE

# Map AMS slots to Spoolman spool IDs
# Format: slot:spool_id,slot:spool_id,...
# AMS slots are numbered 0-3 (starting from 0)
SPOOLMAN_MQTT_AMS_MAPPINGS=0:123,1:456,2:789,3:101
```

### AMS Slot Mapping Explained

The `SPOOLMAN_MQTT_AMS_MAPPINGS` variable maps each AMS slot to a Spoolman spool ID:

- **Slot 0** (top-left position) → Spool ID 123
- **Slot 1** (top-right position) → Spool ID 456
- **Slot 2** (bottom-left position) → Spool ID 789
- **Slot 3** (bottom-right position) → Spool ID 101

You can map any combination of slots. If a slot is not mapped, it will be ignored.

## Step 6: Restart Spoolman

After configuring the environment variables, restart Spoolman:

**Docker:**
```bash
docker-compose down
docker-compose up -d
```

**Standalone:**
```bash
# Stop Spoolman
# Then start it again
```

## Step 7: Verify Connection

Check the Spoolman logs to verify the MQTT connection:

**Docker:**
```bash
docker-compose logs -f spoolman
```

You should see messages like:
```
spoolman  | Setting up MQTT client for Bambu Lab integration...
spoolman  | Initialized Bambu Lab MQTT client for device 01S00A123456789 at 192.168.1.100:8883 with 4 AMS mappings
spoolman  | Starting Bambu Lab MQTT client...
spoolman  | Connecting to 192.168.1.100:8883 (TLS: True)
spoolman  | Connected to Bambu Lab printer MQTT broker
spoolman  | Subscribed to device/01S00A123456789/report
```

## Step 8: Start a Print

1. Load filament in your AMS
2. Start a print job
3. Monitor the Spoolman web interface - you should see spool weights updating automatically

## Troubleshooting

### Connection Failed

- **Verify printer IP**: Make sure the IP address is correct
- **Check LAN-Only Mode**: Ensure it's enabled on the printer
- **Verify password**: Double-check the access code
- **Network connectivity**: Ensure Spoolman can reach the printer (ping test)
- **Firewall**: Make sure port 8883 is not blocked

### No Updates Showing

- **Check mappings**: Verify AMS slot numbers match your configuration
- **Spool IDs**: Ensure the spool IDs in the mapping exist in Spoolman
- **Initial weight**: Make sure spools have an `initial_weight` set
- **AMS loaded**: Ensure filament is loaded in the AMS slots

### Certificate Errors

The integration disables certificate verification because Bambu Lab printers use self-signed certificates. This is normal and secure for local network communication.

## Docker Compose Example

Here's a complete Docker Compose example with MQTT enabled:

```yaml
version: '3.8'

services:
  spoolman:
    image: ghcr.io/donkie/spoolman:latest
    container_name: spoolman
    restart: unless-stopped
    ports:
      - "7912:8000"
    volumes:
      - ./data:/home/app/.local/share/spoolman
    environment:
      - TZ=America/New_York
      - SPOOLMAN_DB_TYPE=sqlite

      # MQTT Configuration
      - SPOOLMAN_MQTT_ENABLED=TRUE
      - SPOOLMAN_MQTT_HOST=192.168.1.100
      - SPOOLMAN_MQTT_PORT=8883
      - SPOOLMAN_MQTT_USERNAME=bblp
      - SPOOLMAN_MQTT_PASSWORD=12345678
      - SPOOLMAN_MQTT_DEVICE_SERIAL=01S00A123456789
      - SPOOLMAN_MQTT_TLS=TRUE
      - SPOOLMAN_MQTT_AMS_MAPPINGS=0:1,1:2,2:3,3:4
```

## How It Works

1. **Connection**: Spoolman connects to your printer's MQTT broker on port 8883
2. **Subscription**: Subscribes to `device/<serial>/report` topic
3. **Monitoring**: Receives real-time print status messages (JSON format)
4. **Parsing**: Extracts AMS filament data (remaining percentage and weight)
5. **Updates**: Calculates remaining weight and updates corresponding spools
6. **WebSocket**: Broadcasts updates to connected clients via Spoolman's WebSocket

## Data Flow

```
Bambu Lab Printer
      ↓ (MQTT)
Spoolman MQTT Client
      ↓
Spoolman Database
      ↓ (WebSocket)
Home Assistant / Web UI
```

## Home Assistant Integration

The MQTT integration works seamlessly with Home Assistant:

1. **Automatic Updates**: Spoolman updates spools in real-time
2. **HA Sensors**: The [spoolman-homeassistant](https://github.com/Disane87/spoolman-homeassistant) integration will reflect these updates
3. **Automations**: Create automations based on spool levels (e.g., notifications when filament is low)

## Security Notes

- **Local Network Only**: This integration only works on your local network
- **TLS Encryption**: All communication is encrypted with TLS/SSL
- **Self-Signed Certs**: Bambu Lab uses self-signed certificates (normal for local devices)
- **Access Code**: Keep your LAN-Only Mode access code secure

## Advanced Configuration

### Multiple Printers

To track multiple Bambu Lab printers, you'll need to run separate Spoolman instances or extend the integration to support multiple devices (future enhancement).

### Update Frequency

The MQTT client receives updates whenever the printer publishes data (typically every few seconds during printing). Spoolman only updates the database when the remaining percentage changes by more than 0.5% to reduce unnecessary writes.

## FAQ

**Q: Does this work wirelessly?**
A: Yes! As long as Spoolman and your printer are on the same network (WiFi or Ethernet).

**Q: Do I need Bambu Handy or Bambu Studio?**
A: No, the integration connects directly to the printer via MQTT.

**Q: Does this work without AMS?**
A: The integration is designed for AMS units. Manual filament tracking is not currently supported.

**Q: Can I use this with OctoPrint or Klipper?**
A: This integration is specifically for Bambu Lab printers. OctoPrint and Klipper have their own Spoolman integrations.

**Q: Will this work on Mac/Windows/Linux?**
A: Yes, it works on any platform that can run Docker or Python.

## Support

If you encounter issues:

1. Check the Spoolman logs for error messages
2. Verify all configuration settings
3. Open an issue on the [Spoolman GitHub repository](https://github.com/Donkie/Spoolman/issues)

## Contributing

This integration is open source! Contributions, bug reports, and feature requests are welcome.
