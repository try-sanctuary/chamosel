#!/bin/sh
set -eu

mkdir -p /data
chown -R chamosel:chamosel /data

exec su-exec chamosel python controller.py
