
## TaskbarHider Pro (Windows 11)

# Goals:
- Fully hide the Windows system taskbar (Explorer) and block mouse-triggered reveal
- Keep third-party taskbar managers (e.g., YASB Reborn) working — hide ONLY Explorer's taskbar
- On Win key press, temporarily show the taskbar for 10 seconds (press Win again to hide immediately)
- Restore everything safely on exit (Alt+`)
- Minimal dependencies (ctypes only), no admin required (recommended but not mandatory)

# Notes:
- Work-area expansion (reclaiming bottom space) is applied only when no third‑party taskbar managers are detected.
- Uses continuous enforcement thread to prevent re-appearance.
- Reactivates blocking after each hide via a short Show→Hide cycle.
"""

## 🚀 Installation

### Prerequisites
- Windows 11
- Python 3.6+ (for source code)
- Administrator privileges (recommended)

### Quick Start
1. **Download the standalone EXE**:
   ```
   TaskbarHider.exe (8.2 MB)
   ```

2. **Or run from source**:
   ```bash
   python final_solution_explained.py
   ```

### Building from Source
```bash
# Install PyInstaller
pip install pyinstaller

# Build standalone EXE
pyinstaller --onefile --noconsole --name="TaskbarHider" final_solution_explained.py
```

## 💻 Usage

### Controls
- **Win Key**: Show taskbar and Start menu for 10 seconds
- **Alt + `**: Exit and restore system
- **Ctrl + C**: Emergency exit

### Execution
```bash
# Python version
python final_solution_explained.py

# Standalone EXE
TaskbarHider.exe
```

The program runs immediately without confirmation prompts and provides real-time status updates.

## 🔧 Alternative Solutions

For complete 48-pixel space reclamation, consider:

**Windhawk + taskbar-height mod** (Recommended)
   - System hooks implementation
   - Complete space reclamation
   - Community supported

## 🤝 Contributing

Contributions welcome! Areas of interest:
- Alternative Windows API approaches
- Performance optimizations
- Additional Windows version support

## 📜 License

This project is provided as-is for educational and personal use. Users are responsible for compliance with their local regulations and Windows license agreements.

## 🙏 Acknowledgments

- Windows API documentation community
- PyInstaller development team
- Windows 11 reverse engineering researchers
- Stack Overflow contributors for Windows internals insights

---

**⚠️ Disclaimer**: This software modifies system behavior. Use at your own risk and ensure you understand the implications. Always test in a safe environment first.

**🎯 Status**: Production Ready | Actively Maintained | Windows 11 Compatible
