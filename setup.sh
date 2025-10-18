#!/bin/bash
# Setup script for YouTube Playlist Auto-Downloader

set -e  # Exit on error

echo "======================================"
echo "YouTube Playlist Auto-Downloader Setup"
echo "======================================"
echo ""

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored messages
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Check Python installation
echo "Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    print_success "Python $PYTHON_VERSION found"
else
    print_error "Python 3 is not installed"
    echo "Please install Python 3.7 or higher from https://www.python.org/"
    exit 1
fi

# Check Python version
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 7 ]); then
    print_error "Python 3.7 or higher is required"
    exit 1
fi

# Check yt-dlp installation
echo ""
echo "Checking yt-dlp installation..."
if command -v yt-dlp &> /dev/null; then
    YT_DLP_VERSION=$(yt-dlp --version)
    print_success "yt-dlp $YT_DLP_VERSION found"
else
    print_warning "yt-dlp is not installed"
    echo "Installing yt-dlp..."

    if command -v brew &> /dev/null; then
        # macOS with Homebrew
        brew install yt-dlp
    else
        # Use pip
        pip3 install yt-dlp
    fi

    if command -v yt-dlp &> /dev/null; then
        print_success "yt-dlp installed successfully"
    else
        print_error "Failed to install yt-dlp"
        exit 1
    fi
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
if pip3 install -r requirements.txt; then
    print_success "Python dependencies installed"
else
    print_error "Failed to install dependencies"
    exit 1
fi

# Check if config.json has been configured
echo ""
echo "Checking configuration..."
if grep -q "YOUR_PLAYLIST_ID_HERE" config.json; then
    print_warning "config.json needs to be configured"
    echo ""
    echo "Please edit config.json and set your playlist URL:"
    echo "  1. Open config.json in a text editor"
    echo "  2. Replace 'YOUR_PLAYLIST_ID_HERE' with your YouTube playlist URL"
    echo "  3. Example: https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxx"
    echo ""
    CONFIGURED=false
else
    print_success "config.json appears to be configured"
    CONFIGURED=true
fi

# Make scripts executable
echo ""
echo "Making scripts executable..."
chmod +x downloader.py scheduler.py setup.sh
print_success "Scripts are now executable"

# Create directories
echo ""
echo "Creating directories..."
DOWNLOAD_PATH=$(python3 -c "import json; print(json.load(open('config.json'))['download_path'])")
mkdir -p "$DOWNLOAD_PATH"
print_success "Download directory created: $DOWNLOAD_PATH"

# Final instructions
echo ""
echo "======================================"
echo "Setup Complete!"
echo "======================================"
echo ""

if [ "$CONFIGURED" = false ]; then
    echo "Next steps:"
    echo "  1. Edit config.json and set your playlist URL"
    echo "  2. Run: python3 scheduler.py"
else
    echo "You're ready to start!"
    echo ""
    echo "Usage:"
    echo "  - One-time download:   python3 downloader.py"
    echo "  - Continuous monitor:  python3 scheduler.py"
    echo ""
    echo "To run in background:"
    echo "  nohup python3 scheduler.py &"
fi

echo ""
echo "See README.md for more information"
echo ""
