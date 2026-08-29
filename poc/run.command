#!/bin/bash
# Chạy lệnh POC dưới TCC identity của Terminal.app. Args đọc từ poc/out/cmd.txt
cd "/Users/tientran/Tong Hop/path_of_kings_tool"
mkdir -p poc/out
ARGS=$(cat poc/out/cmd.txt 2>/dev/null)
{ eval "./.venv/bin/python $ARGS"; } > poc/out/run.log 2>&1
echo "DONE" >> poc/out/run.log
