"""On-device provisioning agent for InkyCal.

Lets the companion app set up WiFi (over Bluetooth) and deliver the Google
OAuth token (over WiFi) without ever attaching a keyboard to the Pi. It only
runs while setup mode is on, and only accepts changes that carry the one-time
code shown on the panel (see agent.py and inkycal.setupmode).
"""
