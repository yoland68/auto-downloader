#!/usr/bin/env python3
"""
Test script to verify the YouTube Playlist Auto-Downloader setup.
Run this after setup.sh to ensure everything is configured correctly.
"""

import sys
import json
import subprocess
from pathlib import Path


def print_status(test_name, passed, message=""):
    """Print test result with formatting."""
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"{status}: {test_name}")
    if message:
        print(f"       {message}")


def test_python_version():
    """Check Python version is 3.7+"""
    version = sys.version_info
    passed = version.major >= 3 and version.minor >= 7
    print_status(
        "Python version",
        passed,
        f"Python {version.major}.{version.minor}.{version.micro} found"
    )
    return passed


def test_yt_dlp():
    """Check if yt-dlp is installed and working"""
    try:
        result = subprocess.run(
            ['yt-dlp', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        passed = result.returncode == 0
        version = result.stdout.strip() if passed else "Not found"
        print_status("yt-dlp installation", passed, f"Version: {version}")
        return passed
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print_status("yt-dlp installation", False, "Not found or not working")
        return False


def test_config_file():
    """Check if config.json exists and is valid"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)

        # Check if configured
        url = config.get('playlist_url', '')
        is_configured = 'YOUR_PLAYLIST_ID_HERE' not in url

        print_status(
            "Configuration file",
            True,
            "Valid JSON found"
        )

        print_status(
            "Playlist URL configured",
            is_configured,
            url if is_configured else "Please set your playlist URL"
        )

        return True, is_configured
    except FileNotFoundError:
        print_status("Configuration file", False, "config.json not found")
        return False, False
    except json.JSONDecodeError:
        print_status("Configuration file", False, "Invalid JSON")
        return False, False


def test_dependencies():
    """Check if Python dependencies are installed"""
    try:
        import schedule
        print_status("Python dependencies", True, "schedule module found")
        return True
    except ImportError:
        print_status(
            "Python dependencies",
            False,
            "Run: pip install -r requirements.txt"
        )
        return False


def test_directories():
    """Check if necessary directories can be created"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)

        download_path = Path(config.get('download_path', './downloads'))
        download_path.mkdir(parents=True, exist_ok=True)

        passed = download_path.exists() and download_path.is_dir()
        print_status(
            "Download directory",
            passed,
            f"Path: {download_path.absolute()}"
        )
        return passed
    except Exception as e:
        print_status("Download directory", False, str(e))
        return False


def test_scripts_executable():
    """Check if main scripts are executable"""
    scripts = ['downloader.py', 'scheduler.py']
    all_passed = True

    for script in scripts:
        path = Path(script)
        passed = path.exists() and path.stat().st_mode & 0o111
        print_status(f"{script} executable", passed)
        all_passed = all_passed and passed

    return all_passed


def main():
    """Run all tests and report results"""
    print("=" * 60)
    print("YouTube Playlist Auto-Downloader - Setup Test")
    print("=" * 60)
    print()

    results = []

    # Run tests
    results.append(("Python version", test_python_version()))
    results.append(("yt-dlp", test_yt_dlp()))

    config_valid, config_ready = test_config_file()
    results.append(("Configuration", config_valid))

    results.append(("Dependencies", test_dependencies()))
    results.append(("Directories", test_directories()))
    results.append(("Scripts", test_scripts_executable()))

    # Summary
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    print(f"Tests passed: {passed}/{total}")
    print()

    if passed == total and config_ready:
        print("✓ All tests passed! System is ready to use.")
        print()
        print("Next steps:")
        print("  1. Run: python3 scheduler.py")
        print("  2. Or use: ./start.sh")
        return 0
    elif passed == total and not config_ready:
        print("⚠ Setup complete, but configuration needed.")
        print()
        print("Next steps:")
        print("  1. Edit config.json and set your playlist URL")
        print("  2. Run: python3 scheduler.py")
        return 1
    else:
        print("✗ Some tests failed. Please fix the issues above.")
        print()
        print("Common fixes:")
        print("  - Install yt-dlp: pip install yt-dlp")
        print("  - Install dependencies: pip install -r requirements.txt")
        print("  - Make scripts executable: chmod +x *.py *.sh")
        return 1


if __name__ == "__main__":
    sys.exit(main())
