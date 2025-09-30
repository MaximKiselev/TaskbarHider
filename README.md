
## TaskbarHider Pro (Windows 11)

# Goals:
- Fully hide the Windows system taskbar (Explorer) and block mouse-triggered reveal
- Keep third-party taskbar managers (e.g., YASB Reborn) working — hide ONLY Explorer's taskbar
- On Win key press, temporarily show the taskbar for 10 seconds (press Win again to hide immediately)
- Restore everything safely on exit (Alt+`)
- CPU load 0%, memory load approximately 0.9 MB

# Notes:
- Work-area expansion (reclaiming bottom space) is applied only when no third‑party taskbar managers are detected.
- Uses continuous enforcement thread to prevent re-appearance.
- Reactivates blocking after each hide via a short Show→Hide cycle.

## Installation
Download the standalone [exe](https://github.com/MaximKiselev/TaskbarHider/releases/download/v0.0.3/TaskbarHiderPro.exe)

### Building from Source
```bash
# Build with MinGW
g++ -std=c++20 -O2 -municode -mwindows final_solution_cpp.cpp -o TaskbarHiderPro.exe \
    -static-libstdc++ -static-libgcc -static \
    -luser32 -lshell32 -lkernel32 -lpthread


```

## Usage

### Controls
- **Win Key**: Show taskbar and Start menu for 10 seconds
- **Alt + `**: Exit and restore system

The program runs immediately without confirmation prompts and provides real-time status updates.

