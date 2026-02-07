#!/bin/bash
nohup python3 monitor.py > monitor.log 2>&1 &
echo "Monitor started with PID $!"
echo "Logs are being written to monitor.log"
