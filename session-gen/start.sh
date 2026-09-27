#!/bin/bash
set -e

cd /home/runner/workspace/attached_assets/extracted/session-gen

export PYTHONPATH=/home/runner/workspace/.pythonlibs/lib/python3.11/site-packages:$PYTHONPATH

exec /home/runner/workspace/.pythonlibs/bin/python3 app.py
