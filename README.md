# InkyCal (Pi Zero 2 W + Inky Impressions 13.3)

Displays today's merged Google + iCloud calendar schedule in portrait mode.
- Polls every 15 minutes
- Updates only if schedule changed
- Shows a "Sleeping..." banner once at sleep start
- Weekly deep clean refresh

## Setup

1) Copy repo to /opt/inkycal
sudo mkdir -p /opt/inkycal
sudo chown -R $USER:$USER /opt/inkycal
# copy files here (git clone or scp)

2) Install
cd /opt/inkycal
./scripts/install.sh

3) Configure
cp config.yaml.example /opt/inkycal/config.yaml
cp .env.example /opt/inkycal/.env
nano /opt/inkycal/config.yaml
nano /opt/inkycal/.env
