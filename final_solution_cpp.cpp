// TaskbarHider Pro (Windows 11) — headless GUI (no console/no tray/no logs)
// Вариант A: при повторном Win — скрытие без «реактивации» (Show→Hide) чтобы убрать «миг».
//
// - Скрывает только системную панель задач Explorer и блокирует появление по наведению
// - Сторонние панели (YASB и пр.) не трогает
// - Win: временный показ на 10 сек (повторное Win — мгновенно скрыть без мигания)
// - Alt+` — выход с восстановлением
// - Поток «дожима» скрытия
// - Расширение рабочей области только при отсутствии сторонних менеджеров

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <shellapi.h>
#include <tlhelp32.h>
#include <vector>
#include <string>
#include <thread>
#include <atomic>
#include <algorithm>
#include <cwctype>

#ifndef ABM_SETSTATE
#define ABM_SETSTATE 0x0000000A
#endif
#ifndef ABS_AUTOHIDE
#define ABS_AUTOHIDE 0x0000001
#endif
#ifndef ABS_ALWAYSONTOP
#define ABS_ALWAYSONTOP 0x0000002
#endif

// --- Globals/State ---
static std::vector<HWND> g_explorer_taskbars;
static std::vector<HWND> g_third_party_taskbars;
static bool g_has_taskbar_managers = false;

static std::atomic<bool> g_exit_flag{false};
static std::atomic<bool> g_desired_hidden{true};
static std::atomic<bool> g_panel_temp_visible{false};
static std::atomic<ULONGLONG> g_show_deadline_ms{0};

static RECT g_original_work_area{};
static bool g_has_original_work_area = false;

// --- Utils ---
static inline ULONGLONG now_ms() { return GetTickCount64(); }
static inline bool key_down(int vk) { return (GetAsyncKeyState(vk) & 0x8000) != 0; }

static std::wstring to_lower(std::wstring s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](wchar_t c){ return (wchar_t)towlower(c); });
    return s;
}

static bool ends_with_icase(const std::wstring& s, const std::wstring& suf) {
    if (s.size() < suf.size()) return false;
    std::wstring a = to_lower(s);
    std::wstring b = to_lower(suf);
    return a.compare(a.size() - b.size(), b.size(), b) == 0;
}

// --- Detect managers (через Toolhelp, без tasklist) ---
static bool detect_taskbar_managers() {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return false;

    const wchar_t* managers[] = {
        L"yasb.exe", L"taskbarx.exe", L"explorerpatcher.exe", L"startallback.exe",
        L"translucent-tb.exe", L"rainmeter.exe", L"displayfusion.exe"
    };

    PROCESSENTRY32W pe{}; pe.dwSize = sizeof(pe);
    bool found = false;
    if (Process32FirstW(snap, &pe)) {
        do {
            std::wstring exe = to_lower(pe.szExeFile);
            for (auto m : managers) {
                if (exe == to_lower(std::wstring(m))) { found = true; break; }
            }
            if (found) break;
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
    return found;
}

// --- Get process path of window (для разделения Explorer vs прочие) ---
static std::wstring get_window_process_path(HWND hwnd) {
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (!pid) return L"";
    HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!h) return L"";
    wchar_t buf[1024]; DWORD len = 1024;
    std::wstring path;
    if (QueryFullProcessImageNameW(h, 0, buf, &len)) path.assign(buf, len);
    CloseHandle(h);
    return path;
}

static void enumerate_taskbars() {
    g_explorer_taskbars.clear();
    g_third_party_taskbars.clear();

    const wchar_t* classes[] = { L"Shell_TrayWnd", L"Shell_SecondaryTrayWnd" };
    for (auto cls : classes) {
        // Primary через FindWindowW
        if (lstrcmpW(cls, L"Shell_TrayWnd") == 0) {
            HWND primary = FindWindowW(cls, nullptr);
            if (primary) {
                std::wstring p = to_lower(get_window_process_path(primary));
                if (ends_with_icase(p, L"\\explorer.exe") || ends_with_icase(p, L"/explorer.exe"))
                    g_explorer_taskbars.push_back(primary);
                else
                    g_third_party_taskbars.push_back(primary);
            }
        }
        // Все окна этого класса
        HWND prev = nullptr;
        while (true) {
            HWND h = FindWindowExW(nullptr, prev, cls, nullptr);
            if (!h) break;
            prev = h;
            if (std::find(g_explorer_taskbars.begin(), g_explorer_taskbars.end(), h) != g_explorer_taskbars.end() ||
                std::find(g_third_party_taskbars.begin(), g_third_party_taskbars.end(), h) != g_third_party_taskbars.end())
                continue;
            std::wstring p = to_lower(get_window_process_path(h));
            if (ends_with_icase(p, L"\\explorer.exe") || ends_with_icase(p, L"/explorer.exe"))
                g_explorer_taskbars.push_back(h);
            else
                g_third_party_taskbars.push_back(h);
        }
    }
}

// --- Work area ---
static void save_work_area() {
    RECT r{};
    if (SystemParametersInfoW(SPI_GETWORKAREA, 0, &r, 0)) {
        g_original_work_area = r;
        g_has_original_work_area = true;
    }
}

static void broadcast_workarea_change() {
    SendMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, (WPARAM)SPI_SETWORKAREA, 0);
}

static void set_fullscreen_work_area() {
    RECT full{0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN)};
    if (SystemParametersInfoW(SPI_SETWORKAREA, 0, &full, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)) {
        broadcast_workarea_change();
    }
}

static void restore_work_area() {
    if (!g_has_original_work_area) return;
    if (SystemParametersInfoW(SPI_SETWORKAREA, 0, &g_original_work_area, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)) {
        broadcast_workarea_change();
    }
}

// --- Taskbar control ---
static void force_hide_hwnd(HWND hwnd) {
    ShowWindow(hwnd, SW_HIDE);
    SetWindowPos(hwnd, nullptr, -10000, -10000, 1, 1,
                 SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
}

static void hide_system_taskbars(bool reactivate = true) {
    for (HWND hwnd : g_explorer_taskbars) {
        if (reactivate) {
            for (int i = 0; i < 2; ++i) {
                ShowWindow(hwnd, SW_SHOWNOACTIVATE);
                Sleep(50);
                ShowWindow(hwnd, SW_HIDE);
                Sleep(50);
            }
        } else {
            // Без «реактивации»: просто скрываем
            ShowWindow(hwnd, SW_HIDE);
        }
        force_hide_hwnd(hwnd);
    }
}

static void show_system_taskbars() {
    for (HWND hwnd : g_explorer_taskbars) {
        ShowWindow(hwnd, SW_SHOWNOACTIVATE);
    }
}

static void close_start_menu() {
    keybd_event(VK_ESCAPE, 0, 0, 0);
    Sleep(20);
    keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0);
}

static HWND get_primary_taskbar_hwnd() {
    if (!g_explorer_taskbars.empty()) return g_explorer_taskbars[0];
    return FindWindowW(L"Shell_TrayWnd", nullptr);
}

static void set_taskbar_autohide(bool enable) {
    APPBARDATA abd{};
    abd.cbSize = sizeof(abd);
    abd.hWnd = get_primary_taskbar_hwnd();
    abd.lParam = enable ? ABS_AUTOHIDE : ABS_ALWAYSONTOP;
    SHAppBarMessage(ABM_SETSTATE, &abd);
}

// --- Enforcement thread ---
static void enforcement_worker() {
    while (!g_exit_flag.load()) {
        if (g_desired_hidden.load() && !g_panel_temp_visible.load()) {
            for (HWND hwnd : g_explorer_taskbars) {
                if (IsWindowVisible(hwnd)) {
                    force_hide_hwnd(hwnd);
                }
            }
        }
        Sleep(100);
    }
}

// --- Entry (GUI subsystem, полностью невидимое приложение) ---
int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    g_has_taskbar_managers = detect_taskbar_managers();
    enumerate_taskbars();
    save_work_area();

    g_desired_hidden = true;
    g_panel_temp_visible = false;
    g_show_deadline_ms = 0;

    set_taskbar_autohide(true);

    hide_system_taskbars(true);
    if (!g_has_taskbar_managers && g_third_party_taskbars.empty()) {
        set_fullscreen_work_area();
    }

    std::thread worker(enforcement_worker);

    bool win_was_down = false;
    bool alt_combo_latched = false;

    // Главный цикл (поллинг клавиш)
    while (!g_exit_flag.load()) {
        ULONGLONG t = now_ms();

        // Alt+` -> выход (по фронту)
        bool alt_down = key_down(VK_MENU);
        bool backtick_down = key_down(VK_OEM_3);
        if (alt_down && backtick_down && !alt_combo_latched) {
            break;
        }
        alt_combo_latched = (alt_down && backtick_down);

        // Win -> показать/скрыть
        bool win_down = key_down(VK_LWIN) || key_down(VK_RWIN);
        if (win_down && !win_was_down) {
            if (!g_panel_temp_visible.load()) {
                // Показ на 10 сек
                g_panel_temp_visible = true;
                g_desired_hidden = false;
                show_system_taskbars();
                if (g_has_original_work_area && (!g_has_taskbar_managers && g_third_party_taskbars.empty())) {
                    restore_work_area();
                }
                g_show_deadline_ms = t + 10000ULL;
                Sleep(120); // debounce
            } else {
                // Раннее скрытие без «мига»: без реактивации
                close_start_menu();
                g_desired_hidden = true;
                g_panel_temp_visible = false;
                hide_system_taskbars(false); // ключевое изменение — без Show→Hide
                if (!g_has_taskbar_managers && g_third_party_taskbars.empty()) {
                    set_fullscreen_work_area();
                }
                Sleep(60);
            }
        }
        win_was_down = win_down;

        // Автоскрытие по таймауту (с реактивацией — как в оригинале)
        if (g_panel_temp_visible.load() && t >= g_show_deadline_ms.load()) {
            close_start_menu();
            g_desired_hidden = true;
            g_panel_temp_visible = false;
            hide_system_taskbars(true);
            if (!g_has_taskbar_managers && g_third_party_taskbars.empty()) {
                set_fullscreen_work_area();
            }
        }

        Sleep(20);
    }

    // Восстановление и выход
    g_exit_flag = true;
    if (worker.joinable()) worker.join();

    g_desired_hidden = false;
    show_system_taskbars();
    restore_work_area();
    set_taskbar_autohide(false);

    return 0;
}
