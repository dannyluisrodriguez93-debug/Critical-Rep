#!/bin/bash
# Account Hub — Mac launcher
# Double-click this file to start the app.
# Your browser will open to http://localhost:5000 automatically.

# Move to the folder where this script lives
cd "$(dirname "$0")"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   Account Hub — Starting..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed."
    echo ""
    echo "Please go to https://www.python.org/downloads/ and install Python 3."
    echo "Then double-click this file again."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

echo "✅ Python found: $(python3 --version)"

# Install/upgrade dependencies quietly
echo ""
echo "Checking dependencies (this only takes a moment)..."
python3 -m pip install -r requirements.txt --quiet --upgrade 2>&1 | grep -v "already satisfied" || true
echo "✅ Dependencies ready"

# Create a .env if it doesn't exist
if [ ! -f ".env" ]; then
    cp .env.example .env 2>/dev/null || true
    echo "✅ Created .env file"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   App is starting..."
echo "   Opening browser to http://localhost:5000"
echo ""
echo "   To stop the app: press Control+C"
echo "   or close this window."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Open browser after 2 seconds
(sleep 2 && open "http://localhost:5000") &

# Start the app
python3 app.py
