#!/bin/sh
if nmcli -t -f DEVICE,STATE device | grep -q '^wlan0:connected$'; then
  exit 0
fi
logger -t shany-wifi-watchdog 'wlan0 desconectado; intentando reconectar'
nmcli radio wifi on >/dev/null 2>&1 || true
nmcli device connect wlan0 >/dev/null 2>&1 || true
nmcli connection up 'Nothing Phone (2)' >/dev/null 2>&1 || nmcli connection up 'wifi_libre' >/dev/null 2>&1 || nmcli connection up 'Galaxy A56 5G 8CFE' >/dev/null 2>&1 || nmcli connection up 'Xiaomi 12' >/dev/null 2>&1 || nmcli connection up 'OPPO A80 5G' >/dev/null 2>&1 || nmcli connection up 'HNERM' >/dev/null 2>&1 || true
