#define WIN32_LEAN_AND_MEAN
#include "probe.h"
#include "host_compat.h"
#include <shellapi.h>
#include <winver.h>
#include <algorithm>
#include <cstdint>
#include <iterator>
#include <sstream>
#include <string>
#include <vector>
#include <memory>

#ifndef _WIN64
#error This controller must be compiled for x64 Windows.
#endif

namespace {
constexpr wchar_t kControllerClass[] = L"TalkHelper.Embedded.Controller.v8";
constexpr wchar_t kSelfTestClass[] = L"TalkHelper.Embedded.SelfTestParent.v8";
constexpr int kStartButton = 101;
constexpr int kRemoveButton = 102;
constexpr int kRefreshButton = 103;
constexpr int kCloseButton = 104;

struct Handle {
    HANDLE value = nullptr;
    explicit Handle(HANDLE h = nullptr) : value(h) {}
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
};

struct Module {
    HMODULE value = nullptr;
    ~Module() { if (value) FreeLibrary(value); }
};

struct Target {
    HWND hwnd = nullptr;
    DWORD pid = 0;
    DWORD thread = 0;
};

struct Controller {
    HWND window = nullptr;
    HWND intro = nullptr;
    HWND status = nullptr;
    HWND buttons[4]{};
    HFONT font = nullptr;
    UINT dpi = 96;
};

std::wstring WinError(DWORD error) {
    wchar_t* buffer = nullptr;
    const DWORD count = FormatMessageW(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr, error, 0, reinterpret_cast<wchar_t*>(&buffer), 0, nullptr);
    std::wstring text = count && buffer ? std::wstring(buffer, count) : L"未知系统错误";
    if (buffer) LocalFree(buffer);
    while (!text.empty() && (text.back() == L'\r' || text.back() == L'\n')) text.pop_back();
    return text + L"（" + std::to_wstring(error) + L"）";
}

bool EqualText(const std::wstring& a, const std::wstring& b) {
    return CompareStringOrdinal(a.c_str(), -1, b.c_str(), -1, TRUE) == CSTR_EQUAL;
}

std::wstring ExecutableDirectory() {
    std::vector<wchar_t> buffer(32768);
    const DWORD size = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (!size || size >= buffer.size()) return {};
    std::wstring path(buffer.data(), size);
    const auto separator = path.find_last_of(L"\\/");
    return separator == std::wstring::npos ? std::wstring() : path.substr(0, separator + 1);
}

std::wstring ProcessImage(HANDLE process) {
    std::vector<wchar_t> buffer(32768);
    DWORD size = static_cast<DWORD>(buffer.size());
    if (!QueryFullProcessImageNameW(process, 0, buffer.data(), &size)) return {};
    std::wstring path(buffer.data(), size);
    std::replace(path.begin(), path.end(), L'/', L'\\');
    return path;
}

bool TokenUserBytes(HANDLE process, std::vector<BYTE>& buffer) {
    HANDLE rawToken = nullptr;
    if (!OpenProcessToken(process, TOKEN_QUERY, &rawToken)) return false;
    Handle token(rawToken);
    DWORD needed = 0;
    GetTokenInformation(token.value, TokenUser, nullptr, 0, &needed);
    if (!needed) return false;
    buffer.resize(needed);
    return GetTokenInformation(token.value, TokenUser, buffer.data(), needed, &needed) != FALSE;
}

bool SameUser(HANDLE process) {
    std::vector<BYTE> ours, theirs;
    if (!TokenUserBytes(GetCurrentProcess(), ours) || !TokenUserBytes(process, theirs)) return false;
    const auto localUser = reinterpret_cast<const TOKEN_USER*>(ours.data());
    const auto targetUser = reinterpret_cast<const TOKEN_USER*>(theirs.data());
    return EqualSid(localUser->User.Sid, targetUser->User.Sid) != FALSE;
}

bool IsNativeX64(HANDLE process) {
    using IsWow64Process2Fn = BOOL (WINAPI*)(HANDLE, USHORT*, USHORT*);
    const auto query = reinterpret_cast<IsWow64Process2Fn>(
        GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "IsWow64Process2"));
    if (!query) return false;  // Do not guess architecture on an unsupported OS.
    USHORT processMachine = 0, nativeMachine = 0;
    return query(process, &processMachine, &nativeMachine)
        && processMachine == IMAGE_FILE_MACHINE_UNKNOWN
        && nativeMachine == IMAGE_FILE_MACHINE_AMD64;
}

std::wstring FileVersion(const std::wstring& path) {
    DWORD unused = 0;
    const DWORD size = GetFileVersionInfoSizeW(path.c_str(), &unused);
    if (!size) return {};
    std::vector<BYTE> bytes(size);
    if (!GetFileVersionInfoW(path.c_str(), 0, size, bytes.data())) return {};
    VS_FIXEDFILEINFO* version = nullptr;
    UINT length = 0;
    if (!VerQueryValueW(bytes.data(), L"\\", reinterpret_cast<void**>(&version), &length)
            || length < sizeof(VS_FIXEDFILEINFO) || version->dwSignature != 0xFEEF04BD) return {};
    return std::to_wstring(HIWORD(version->dwFileVersionMS)) + L"."
        + std::to_wstring(LOWORD(version->dwFileVersionMS)) + L"."
        + std::to_wstring(HIWORD(version->dwFileVersionLS)) + L"."
        + std::to_wstring(LOWORD(version->dwFileVersionLS));
}

bool BasicWindowMatches(HWND hwnd) {
    if (!IsWindow(hwnd) || !IsWindowVisible(hwnd) || IsIconic(hwnd)
            || GetWindow(hwnd, GW_OWNER) || GetAncestor(hwnd, GA_ROOT) != hwnd) return false;
    wchar_t title[256]{};
    if (!GetWindowTextW(hwnd, title, static_cast<int>(std::size(title)))) return false;
    if (std::wstring(title) != L"微信" && std::wstring(title) != L"WeChat") return false;
    RECT rect{};
    return GetWindowRect(hwnd, &rect) && rect.right - rect.left >= 640 && rect.bottom - rect.top >= 420;
}

BOOL CALLBACK CollectCandidates(HWND hwnd, LPARAM parameter) {
    if (!BasicWindowMatches(hwnd)) return TRUE;
    DWORD pid = 0;
    const DWORD thread = GetWindowThreadProcessId(hwnd, &pid);
    if (!thread || !pid || pid == GetCurrentProcessId()) return TRUE;
    Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid));
    if (!process.value) return TRUE;
    const std::wstring image = ProcessImage(process.value);
    const auto separator = image.find_last_of(L'\\');
    const std::wstring basename = image.substr(separator == std::wstring::npos ? 0 : separator + 1);
    if (EqualText(basename, L"Weixin.exe")) {
        reinterpret_cast<std::vector<Target>*>(parameter)->push_back({hwnd, pid, thread});
    }
    return TRUE;
}

bool ValidateTarget(const Target& target, std::wstring& reason) {
    DWORD currentPid = 0;
    if (!BasicWindowMatches(target.hwnd)
            || GetWindowThreadProcessId(target.hwnd, &currentPid) != target.thread
            || currentPid != target.pid) {
        reason = L"目标窗口已关闭或改变，请刷新状态。";
        return false;
    }
    Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, target.pid));
    if (!process.value) {
        reason = L"无法以当前用户权限验证微信进程：" + WinError(GetLastError());
        return false;
    }
    const std::wstring image = ProcessImage(process.value);
    if (!hostcompat::basenameIs(image,L"Weixin.exe")) {
        reason = L"目标不是微信主程序，未执行加载。";
        return false;
    }
    if (!IsNativeX64(GetCurrentProcess()) || !IsNativeX64(process.value)) {
        reason = L"仅支持本机原生 x64 Windows 和 x64 微信，未执行加载。";
        return false;
    }
    DWORD ourSession = 0, theirSession = 0;
    if (!ProcessIdToSessionId(GetCurrentProcessId(), &ourSession)
            || !ProcessIdToSessionId(target.pid, &theirSession)
            || ourSession != theirSession || !SameUser(process.value)) {
        reason = L"目标不是当前用户、当前登录会话中的微信，未执行加载。";
        return false;
    }
    const std::wstring version = FileVersion(image);
    bool supported=false;
    for(const auto& build:hostcompat::builds)if(version==build.version){supported=true;break;}
    if (!supported) {
        reason = L"微信文件版本不在已验证范围内。支持 4.1.13.65、4.1.15.13；检测到 "
            + (version.empty() ? L"无法读取" : version) + L"。未执行加载。";
        return false;
    }
    const auto* build=hostcompat::exeBuild(image);
    if (!build || version!=build->version) {
        reason = L"微信文件版本正确，但二进制构建与已验证版本不同；未执行加载。";
        return false;
    }
    return true;
}

bool SelectTarget(Target& target, std::wstring& reason) {
    std::vector<Target> candidates;
    if (!EnumWindows(CollectCandidates, reinterpret_cast<LPARAM>(&candidates))) {
        reason = L"无法枚举窗口：" + WinError(GetLastError());
        return false;
    }
    if (candidates.empty()) {
        reason = L"未找到已展开的微信主窗口。请自行打开微信，保持主窗口可见后刷新。\r\n"
                 L"本启动器不会启动微信，也不会请求管理员权限。";
        return false;
    }
    if (candidates.size() != 1) {
        reason = L"发现多个符合标题和进程名的微信主窗口，无法确定唯一目标，未执行加载。";
        return false;
    }
    target = candidates.front();
    return ValidateTarget(target, reason);
}

bool VerifyPanel(HWND panel, const Target& target, std::wstring& reason) {
    DWORD pid = 0;
    const DWORD thread = GetWindowThreadProcessId(panel, &pid);
    wchar_t name[256]{};
    GetClassNameW(panel, name, static_cast<int>(std::size(name)));
    if (!panel || !IsWindow(panel) || std::wstring(name) != kProbeClass
            || GetParent(panel) != target.hwnd
            || !(GetWindowLongPtrW(panel, GWL_STYLE) & WS_CHILD)
            || pid != target.pid || thread != target.thread) {
        reason = L"控件身份校验失败：必须是微信同进程、同 UI 线程的直接 WS_CHILD 子窗口。";
        return false;
    }
    DWORD_PTR proof = 0;
    if (!SendMessageTimeoutW(panel, kQueryProof, 0, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, 3000, &proof)
            || proof != static_cast<DWORD_PTR>(kProofValue)) {
        reason = L"控件证明消息未通过，未将其视为成功的内嵌面板。";
        return false;
    }
    DWORD afterPid = 0;
    if (!IsWindow(panel) || GetParent(panel) != target.hwnd
            || GetWindowThreadProcessId(panel, &afterPid) != target.thread || afterPid != target.pid) {
        reason = L"控件在验证期间发生变化，请刷新状态。";
        return false;
    }
    return true;
}

std::wstring TargetDescription(const Target& target) {
    Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,target.pid));
    const auto version=process.value?FileVersion(ProcessImage(process.value)):L"未知";
    return L"微信 " + version + L" · x64\r\nPID："
        + std::to_wstring(target.pid) + L"　UI 线程：" + std::to_wstring(target.thread);
}

bool LoadProbe(Module& module, std::wstring& reason) {
    const std::wstring directory = ExecutableDirectory();
    if (directory.empty()) {
        reason = L"无法确认本启动器的绝对目录。";
        return false;
    }
    const std::wstring path = directory + kDllName;
    module.value = LoadLibraryExW(path.c_str(), nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module.value) {
        reason = L"无法加载启动器同目录中的测试 DLL：\r\n" + path + L"\r\n" + WinError(GetLastError());
        return false;
    }
    return true;
}

std::wstring RefreshStatus() {
    Target target;
    std::wstring reason;
    if (!SelectTarget(target, reason)) return reason;
    const HWND panel = FindWindowExW(target.hwnd, nullptr, kProbeClass, nullptr);
    if (!panel) return TargetDescription(target) + L"\r\n\r\n目标验证通过，内联聊天视图尚未启用。\r\n点击“启用内联聊天视图”启动。";
    if (!VerifyPanel(panel, target, reason)) return reason;
    return TargetDescription(target) + L"\r\n\r\n内联聊天视图已在微信内部。\r\n"
        L"已验证：直接父子关系、WS_CHILD、同 PID、同 UI 线程、证明消息。\r\n"
        L"气泡通过可见消息定位；不会修改微信聊天记录。";
}

std::wstring StartWorker(HWND panel) {
    DWORD_PTR started = 0;
    if (!SendMessageTimeoutW(panel, kStartWorker, 0, 0,
            SMTO_ABORTIFHUNG | SMTO_BLOCK, 3000, &started) || started != 1) {
        return L"聊天视图已创建，但后台服务启动失败。\r\n请确认 TalkHelperNativeWorker-v13r2 文件夹完整。";
    }
    return L"微信原界面建议已启用，DeepSeek 分析服务正在后台启动。\r\n"
        L"可以关闭启动器。聊天文字从微信直接读取，文字只发往 DeepSeek 官方接口生成建议。\r\n"
        L"原消息和功能由微信保留；只分析文字。复制按钮只复制，不发送消息。";
}

std::wstring StartProbe() {
    Target target;
    std::wstring reason;
    if (!SelectTarget(target, reason)) return reason;
    if (const HWND existing = FindWindowExW(target.hwnd, nullptr, kProbeClass, nullptr)) {
        if (!VerifyPanel(existing, target, reason)) return reason;
        return TargetDescription(target) + L"\r\n\r\n" + StartWorker(existing);
    }
    Module module;
    if (!LoadProbe(module, reason)) return reason;
    const auto procedure = reinterpret_cast<HOOKPROC>(GetProcAddress(module.value, "TalkHelperProbeHookProc"));
    if (!procedure) return L"测试 DLL 缺少 TalkHelperProbeHookProc 导出，未安装 hook。";
    const UINT command = RegisterWindowMessageW(kControlMessage);
    if (!command) return L"无法注册控制消息：" + WinError(GetLastError());
    // Revalidate immediately before attaching to the one selected UI thread.
    if (!ValidateTarget(target, reason)) return reason;
    const HHOOK hook = SetWindowsHookExW(WH_CALLWNDPROC, procedure, module.value, target.thread);
    if (!hook) return L"无法安装本次临时线程 hook：" + WinError(GetLastError());
    DWORD_PTR reply = 0;
    SetLastError(ERROR_SUCCESS);
    const bool delivered = SendMessageTimeoutW(target.hwnd, command, kStartCommand, 0,
        SMTO_ABORTIFHUNG | SMTO_BLOCK, 5000, &reply) != 0;
    const DWORD deliveryError = GetLastError();
    // This is deliberately unconditional: no branch can leave our hook installed.
    const bool unhooked = UnhookWindowsHookEx(hook) != FALSE;
    const DWORD unhookError = unhooked ? ERROR_SUCCESS : GetLastError();
    if (!unhooked) {
        return L"移除临时 hook 时系统返回失败：" + WinError(unhookError)
            + L"\r\n请关闭微信以结束本次实验，不要继续重复加载。";
    }
    const HWND panel = FindWindowExW(target.hwnd, nullptr, kProbeClass, nullptr);
    if (!delivered) {
        return L"控制消息发送失败或超时，临时 hook 已移除：" + WinError(deliveryError)
            + (panel ? L"\r\n检测到测试类窗口；请刷新状态核实，或使用“移除测试面板”。"
                     : L"\r\n未发现测试面板；没有强制终止或修改微信。" );
    }
    if (!VerifyPanel(panel, target, reason)) return reason + L"\r\n临时 hook 已移除。";
    return TargetDescription(target) + L"\r\n\r\n" + StartWorker(panel);
}

std::wstring RemoveProbe() {
    Target target;
    std::wstring reason;
    if (!SelectTarget(target, reason)) return reason;
    const HWND panel = FindWindowExW(target.hwnd, nullptr, kProbeClass, nullptr);
    if (!panel) return L"目前没有测试面板可移除。已加载的 DLL 仍可能驻留至微信退出。";
    if (!VerifyPanel(panel, target, reason)) return reason;
    DWORD_PTR reply = 0;
    if (!SendMessageTimeoutW(panel, WM_CLOSE, 0, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, 3000, &reply)) {
        return L"关闭面板的消息失败或超时：" + WinError(GetLastError())
            + L"\r\n未强行销毁窗口或卸载 DLL。";
    }
    if (FindWindowExW(target.hwnd, nullptr, kProbeClass, nullptr)) {
        return L"关闭消息已送达，但测试面板仍存在，请刷新状态。\r\nDLL 不会被强制卸载。";
    }
    return L"测试面板已移除。\r\n\r\nDLL 仍留在微信当前进程中，退出微信后消失。\r\n"
        L"没有修改微信安装文件、数据库或自动启动设置。";
}

int Pixels(const Controller& controller, int value) { return MulDiv(value, controller.dpi, 96); }

void Layout(Controller& controller) {
    RECT rect{};
    GetClientRect(controller.window, &rect);
    const int margin = Pixels(controller, 22), gap = Pixels(controller, 10);
    const int width = std::max(100, static_cast<int>(rect.right) - margin * 2);
    MoveWindow(controller.intro, margin, margin, width, Pixels(controller, 108), TRUE);
    const int buttonY = Pixels(controller, 143), buttonHeight = Pixels(controller, 40);
    const int buttonWidth = (width - gap) / 2;
    for (int i = 0; i < 4; ++i) {
        MoveWindow(controller.buttons[i], margin + (i % 2) * (buttonWidth + gap),
            buttonY + (i / 2) * (buttonHeight + gap), buttonWidth, buttonHeight, TRUE);
    }
    const int statusY = buttonY + buttonHeight * 2 + gap * 2;
    MoveWindow(controller.status, margin, statusY, width,
        std::max(Pixels(controller, 80), static_cast<int>(rect.bottom) - statusY - margin), TRUE);
}

void CreateControls(Controller& controller) {
    controller.font = CreateFontW(-Pixels(controller, 16), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
        DEFAULT_PITCH | FF_DONTCARE, L"Microsoft YaHei UI");
    controller.intro = CreateWindowExW(0, L"STATIC",
        L"talk helper · 微信内嵌内联聊天视图\r\n适用于已验证的微信 4.1.13.65 / 4.1.15.13（x64）。\r\n"
        L"直接读取当前微信聊天文字，直连 DeepSeek；点击复制后由你决定发送。",
        WS_CHILD | WS_VISIBLE, 0, 0, 0, 0, controller.window, nullptr, GetModuleHandleW(nullptr), nullptr);
    const wchar_t* labels[] = {L"启用内联聊天视图", L"移除内联聊天视图", L"刷新状态", L"关闭启动器"};
    const int identifiers[] = {kStartButton, kRemoveButton, kRefreshButton, kCloseButton};
    for (int i = 0; i < 4; ++i) {
        controller.buttons[i] = CreateWindowExW(0, L"BUTTON", labels[i],
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | (i == 0 ? BS_DEFPUSHBUTTON : BS_PUSHBUTTON),
            0, 0, 0, 0, controller.window, reinterpret_cast<HMENU>(static_cast<INT_PTR>(identifiers[i])),
            GetModuleHandleW(nullptr), nullptr);
        SendMessageW(controller.buttons[i], WM_SETFONT, reinterpret_cast<WPARAM>(controller.font), TRUE);
    }
    controller.status = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
        WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_LEFT | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY,
        0, 0, 0, 0, controller.window, nullptr, GetModuleHandleW(nullptr), nullptr);
    SendMessageW(controller.intro, WM_SETFONT, reinterpret_cast<WPARAM>(controller.font), TRUE);
    SendMessageW(controller.status, WM_SETFONT, reinterpret_cast<WPARAM>(controller.font), TRUE);
    Layout(controller);
    SetWindowTextW(controller.status, RefreshStatus().c_str());
}

LRESULT CALLBACK ControllerProcedure(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam) {
    auto controller = reinterpret_cast<Controller*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (message == WM_NCCREATE) {
        const auto creation = reinterpret_cast<CREATESTRUCTW*>(lParam);
        controller = static_cast<Controller*>(creation->lpCreateParams);
        controller->window = hwnd;
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(controller));
    }
    if (!controller) return DefWindowProcW(hwnd, message, wParam, lParam);
    switch (message) {
        case WM_CREATE:
            CreateControls(*controller);
            return 0;
        case WM_SIZE:
            if (controller->status) Layout(*controller);
            return 0;
        case WM_GETMINMAXINFO: {
            auto limits = reinterpret_cast<MINMAXINFO*>(lParam);
            limits->ptMinTrackSize = {Pixels(*controller, 500), Pixels(*controller, 480)};
            return 0;
        }
        case WM_COMMAND: {
            if (HIWORD(wParam) != BN_CLICKED) break;
            const int command = LOWORD(wParam);
            if (command == kCloseButton) { DestroyWindow(hwnd); return 0; }
            if (command != kStartButton && command != kRemoveButton && command != kRefreshButton) break;
            for (HWND button : controller->buttons) EnableWindow(button, FALSE);
            SetWindowTextW(controller->status, L"正在验证目标并执行本次操作…");
            UpdateWindow(controller->status);
            std::wstring result;
            try {
                result = command == kStartButton ? StartProbe()
                    : command == kRemoveButton ? RemoveProbe() : RefreshStatus();
            } catch (...) {
                result = L"启动器遇到异常，操作未完成。请刷新状态核实面板，不要重复加载。";
            }
            SetWindowTextW(controller->status, result.c_str());
            for (HWND button : controller->buttons) EnableWindow(button, TRUE);
            return 0;
        }
        case WM_CLOSE:
            DestroyWindow(hwnd);  // Closing the controller intentionally leaves a verified panel running.
            return 0;
        case WM_DESTROY:
            if (controller->font) { DeleteObject(controller->font); controller->font = nullptr; }
            PostQuitMessage(0);
            return 0;
    }
    return DefWindowProcW(hwnd, message, wParam, lParam);
}

bool WriteSelfTestResult(const std::wstring& text, const wchar_t* fileName = L"self-test-result.txt") {
    const std::wstring directory = ExecutableDirectory();
    if (directory.empty()) return false;
    const std::wstring path = directory + fileName;
    Handle file(CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL, nullptr));
    if (file.value == INVALID_HANDLE_VALUE) return false;
    const int size = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()),
        nullptr, 0, nullptr, nullptr);
    if (size <= 0) return false;
    std::vector<char> bytes(size);
    WideCharToMultiByte(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()),
        bytes.data(), size, nullptr, nullptr);
    DWORD written = 0;
    return WriteFile(file.value, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr)
        && written == bytes.size();
}

int SelfTest(HINSTANCE instance) {
    std::wstring report=L"status=FAIL\r\n"; bool passed=false; HWND parent=nullptr; Module module;
    WNDCLASSW cls{};cls.hInstance=instance;cls.lpfnWndProc=DefWindowProcW;cls.lpszClassName=kSelfTestClass;
    const ATOM atom=RegisterClassW(&cls);
    try {
        if(!atom)throw std::wstring(L"Cannot create test host");
        parent=CreateWindowExW(0,kSelfTestClass,L"talk helper isolated test",WS_OVERLAPPEDWINDOW,0,0,1000,700,nullptr,nullptr,instance,nullptr);
        std::wstring reason;if(!parent||!LoadProbe(module,reason))throw reason;
        auto start=reinterpret_cast<ProbeStart>(GetProcAddress(module.value,"TalkHelperProbeStart"));
        auto session=reinterpret_cast<ProbeTestSession>(GetProcAddress(module.value,"TalkHelperTestSession"));
        using Render=BOOL(WINAPI*)(const wchar_t*);
        auto render=reinterpret_cast<Render>(GetProcAddress(module.value,"TalkHelperRenderReference"));
        using OutsideClick=BOOL(WINAPI*)(HWND);
        auto outsideClick=reinterpret_cast<OutsideClick>(GetProcAddress(module.value,"TalkHelperTestOutsideClick"));
        HWND panel=start?start(parent):nullptr;Target local{parent,GetCurrentProcessId(),GetCurrentThreadId()};
        if(!VerifyPanel(panel,local,reason)||start(parent)!=panel)throw std::wstring(L"Panel identity/idempotency failed");
        const std::uint64_t token=0x123456789abcdefULL;
        if(!session||!session(panel,token))throw std::wstring(L"Test session failed");
        auto packet=std::make_unique<BubblePacket>();auto& p=*packet;
        p.magic=kBubbleMagic;p.version=kBubbleVersion;p.token=token;p.sequence=1;p.flags=kFlagAnchored|kFlagHasReply;
        p.area[2]=720;p.area[3]=540;p.tension=4;
        p.anchor[0]=80;p.anchor[1]=180;p.anchor[2]=384;p.anchor[3]=281;
        lstrcpyW(p.title,L"测试会话");lstrcpyW(p.status,L"建议：先核对聊天记录");
        lstrcpyW(p.body,L"理解事实，再说明下一步。不要编造约定。");lstrcpyW(p.reply,L"我先核对一下聊天记录。");
        COPYDATASTRUCT data{kBubbleData,sizeof(p),&p};
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&data))!=1)throw std::wstring(L"Valid packet rejected");
        auto rejected=[&](){return SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&data))==0;};
        if(!rejected())throw std::wstring(L"Sequence not checked");p.sequence=2;p.token++;
        if(!rejected())throw std::wstring(L"Token not checked");p.token=token;p.tension=10;
        if(!rejected())throw std::wstring(L"Tension not checked");p.tension=4;
        p.anchor[1]=10;p.area[1]=60;
        if(!rejected())throw std::wstring(L"Header protection failed");p.anchor[1]=180;
        std::fill(std::begin(p.title),std::end(p.title),L'x');
        if(!rejected())throw std::wstring(L"UTF16 bound not checked");p.title[127]=0;
        p.area[3]=0;if(!rejected())throw std::wstring(L"Empty area not checked");p.area[3]=540;data.cbData--;
        if(!rejected())throw std::wstring(L"Packet size not checked");data.cbData++;
        SendMessageW(panel,WM_COMMAND,kNextButton,0);
        if(SendMessageW(panel,kPollCommands,token+1,0)||SendMessageW(panel,kPollCommands,token,0)!=kCommandNextReply||SendMessageW(panel,kPollCommands,token,0))throw std::wstring(L"Command queue failed");
        if(!render||!render((ExecutableDirectory()+L"card-reference.png").c_str()))throw std::wstring(L"Reference render failed");
        if(!outsideClick||!outsideClick(panel))throw std::wstring(L"Outside click dismissal failed");
        p.sequence=2;p.cardId=1;lstrcpyW(p.title,L"第一条对方消息");
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&data))!=1)throw std::wstring(L"First independent card rejected");
        p.sequence=3;p.cardId=2;p.anchor[1]=300;p.anchor[3]=401;lstrcpyW(p.title,L"第二条对方消息");
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&data))!=1)throw std::wstring(L"Second independent card rejected");
        HWND cardA=FindWindowExW(parent,nullptr,kCardClass,nullptr),cardB=FindWindowExW(parent,cardA,kCardClass,nullptr);
        if(!cardA||!cardB||cardA==cardB||FindWindowExW(parent,nullptr,kProbeClass,nullptr)!=panel)throw std::wstring(L"Card/manager isolation failed");
        auto id=SendMessageW(cardA,kQueryCardId,0,0);SendMessageW(cardA,WM_COMMAND,kNextButton,0);
        if(SendMessageW(panel,kPollCommands,token,0)!=(id<<4|kCommandNextReply))throw std::wstring(L"Per-card command routing failed");
        auto following=reinterpret_cast<OutsideClick>(GetProcAddress(module.value,"TalkHelperTestFollowing"));
        if(!following||!following(panel))throw std::wstring(L"Native following, clipping, or return positioning failed: ")+std::to_wstring(GetLastError());
        struct ListTest {DirectoryHeader header;DirectoryEntry item;} list{};
        list.header={static_cast<std::uint32_t>(kDirectoryData),kBubbleVersion,token,1,1};list.item={1,0,1,L"测试群聊"};
        COPYDATASTRUCT listData{kDirectoryData,sizeof(list),&list};
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&listData))!=1)throw std::wstring(L"Directory rejected");
        list.header.sequence=2;list.header.token++;
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&listData)))throw std::wstring(L"Directory token not checked");
        list.header.token=token;list.item.enabled=2;
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&listData)))throw std::wstring(L"Directory flag not checked");
        #pragma pack(push,1)
        struct LayoutHeaderTest {uint32_t magic,version;uint64_t token,sequence,list;uint32_t count;};
        #pragma pack(pop)
        static_assert(sizeof(LayoutHeaderTest)==36,"Layout header contract");
        LayoutHeaderTest layout{0x54485212,13,token+1,1,0,0};COPYDATASTRUCT layoutData{0x54485212,sizeof(layout),&layout};
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&layoutData)))throw std::wstring(L"Layout token not checked");
        layout.token=token;layout.version=11;
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&layoutData)))throw std::wstring(L"Layout version not checked");
        layout.version=kBubbleVersion;layout.count=1;
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&layoutData)))throw std::wstring(L"Layout size not checked");
        layout.count=0;
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&layoutData))!=1)throw std::wstring(L"Layout clear rejected");
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&layoutData)))throw std::wstring(L"Layout sequence not checked");
        SettingsPacket preferences{};preferences.magic=kSettingsData;preferences.version=kBubbleVersion;preferences.token=token;preferences.sequence=1;preferences.context=12;preferences.flags=1;
        COPYDATASTRUCT settingsData{kSettingsData,sizeof(preferences),&preferences};
        preferences.token++;
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&settingsData)))throw std::wstring(L"Settings token not checked");
        preferences.token=token;preferences.flags=4;
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&settingsData)))throw std::wstring(L"Settings flags not checked");
        preferences.flags=1;preferences.key[0]=L'x';
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&settingsData)))throw std::wstring(L"Settings exposed key");
        preferences.key[0]=0;
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&settingsData))!=1)throw std::wstring(L"Settings rejected");
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&settingsData)))throw std::wstring(L"Settings sequence not checked");
        if(SendMessageW(panel,kQuerySettingsDraft,token+1,0))throw std::wstring(L"Settings draft token not checked");
        SendMessageW(panel,WM_COMMAND,kSettingsButton,0);
        HWND form=FindWindowW(L"TalkHelper.Settings.v13r2",nullptr);
        if(!form||GetWindowThreadProcessId(form,nullptr)!=GetCurrentThreadId())throw std::wstring(L"Settings form not created on host UI thread");
        if(SendMessageW(panel,kPollCommands,token,0)!=5)throw std::wstring(L"Settings load routing failed");
        preferences.sequence=2;lstrcpyW(preferences.assistant,L"talk helper");lstrcpyW(preferences.base,L"https://api.deepseek.com");lstrcpyW(preferences.model,L"deepseek-flash");lstrcpyW(preferences.relationship,L"朋友");
        lstrcpyW(preferences.selfMbti,L"ENFP");lstrcpyW(preferences.otherMbti,L"INTJ");lstrcpyW(preferences.goal,L"了解彼此");
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&settingsData))!=1||!IsWindowEnabled(GetDlgItem(form,411)))throw std::wstring(L"Settings form load failed");
        wchar_t loaded[128]{};GetDlgItemTextW(form,450,loaded,128);
        if(wcscmp(loaded,L"ENFP")||!GetDlgItem(form,431)||!GetDlgItem(form,432))throw std::wstring(L"Profile form load failed");
        SetDlgItemTextW(form,407,L"自然、具体的建议");SetDlgItemTextW(form,408,L"好呀");SetDlgItemTextW(form,404,L"isolated-test-key");
        SetDlgItemTextW(form,450,L"INFP");SetDlgItemTextW(form,456,L"77");SetDlgItemTextW(form,472,L"第一次见面；共同出游；最近聊工作");
        SendMessageW(form,WM_COMMAND,MAKEWPARAM(411,BN_CLICKED),0);
        if(SendMessageW(panel,kPollCommands,token,0)!=6||IsWindowEnabled(GetDlgItem(form,411)))throw std::wstring(L"Settings save routing failed");
        auto* draft=reinterpret_cast<SettingsPacket*>(SendMessageW(panel,kQuerySettingsDraft,token,0));
        if(!draft||draft->token!=token||draft->context!=12||wcscmp(draft->key,L"isolated-test-key")||wcscmp(draft->phrases,L"好呀")
           ||wcscmp(draft->selfMbti,L"INFP")||wcscmp(draft->otherRating,L"77")||wcscmp(draft->recentEvents,L"第一次见面；共同出游；最近聊工作"))throw std::wstring(L"Settings draft round trip failed");
        preferences.sequence=3;preferences.flags=2;lstrcpyW(preferences.status,L"测试校验错误");
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&settingsData))!=1||!IsWindowEnabled(GetDlgItem(form,411))||SendMessageW(panel,kQuerySettingsDraft,token,0))throw std::wstring(L"Settings error recovery failed");
        SendMessageW(form,WM_COMMAND,MAKEWPARAM(411,BN_CLICKED),0);SendMessageW(panel,kPollCommands,token,0);
        preferences.sequence=4;preferences.flags=1;
        if(SendMessageW(panel,WM_COPYDATA,0,reinterpret_cast<LPARAM>(&settingsData))!=1||GetWindowTextLengthW(GetDlgItem(form,404)))throw std::wstring(L"Settings secret not cleared after save");
        SendMessageW(form,WM_CLOSE,0,0);if(IsWindow(form))throw std::wstring(L"Settings form not removed");
        SendMessageW(panel,WM_CLOSE,0,0);if(IsWindow(panel))throw std::wstring(L"Panel still exists");
        if(IsWindow(cardA)||IsWindow(cardB))throw std::wstring(L"Independent cards leaked after removal");
        passed=true;report=L"status=PASS\r\nmode=isolated\r\nsame_process=true\r\nsame_ui_thread=true\r\ndirect_child=true\r\nidempotent=true\r\ncard_only_ipc=true\r\nrejects_token_sequence_size_text_tension_header_area=true\r\ncommand_queue=true\r\nreference_render=true\r\noutside_click_dismissed=true\r\nindependent_cards=true\r\nper_card_commands=true\r\nnative_follow_geometry=true\r\ntop_bottom_clipping=true\r\nreturn_from_offscreen=true\r\nfollow_stats_authentication=true\r\ndirectory_authentication=true\r\nsettings_authentication=true\r\nsettings_form_roundtrip=true\r\nsettings_error_recovery=true\r\nsettings_secret_cleared=true\r\nremoved=true\r\nwechat_accessed=false\r\nnetwork_accessed=false\r\n";
    }catch(const std::wstring& error){report+=L"reason="+error+L"\r\n";}catch(...){report+=L"reason=unexpected exception\r\n";}
    if(parent&&IsWindow(parent))DestroyWindow(parent);if(atom)UnregisterClassW(kSelfTestClass,instance);
    return WriteSelfTestResult(report)&&passed?0:1;
}
}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int showCommand) {
    int count = 0;
    LPWSTR* arguments = CommandLineToArgvW(GetCommandLineW(), &count);
    bool selfTest = false;
    bool headlessStart = false;
    bool headlessRemove = false;
    bool headlessSwitch = false;
    bool openSettings = false;
#ifdef TALKHELPER_SETTINGS
    openSettings = true;
#endif
    const bool defaultAttach = count <= 1;
#ifdef TALKHELPER_HEADLESS_SWITCH
    headlessSwitch = true;
#endif
    if (arguments) {
        for (int i = 1; i < count; ++i) {
            const std::wstring arg(arguments[i]);
            if (arg == L"--self-test") selfTest = true;
            if (arg == L"--start") headlessStart = true;
            if (arg == L"--remove") headlessRemove = true;
            if (arg == L"--settings") {headlessStart=true;openSettings=true;}
        }
        LocalFree(arguments);
    }
    if (selfTest) return SelfTest(instance);
    if (defaultAttach) {
#ifdef TALKHELPER_REMOVE
        headlessRemove = true;
#else
        headlessStart = true;
#endif
    }
    if ((headlessStart && headlessRemove) || (headlessSwitch && (headlessStart || headlessRemove))) return 2;
    using SetDpiFn = BOOL (WINAPI*)(DPI_AWARENESS_CONTEXT);
    const auto setDpi = reinterpret_cast<SetDpiFn>(
        GetProcAddress(GetModuleHandleW(L"user32.dll"), "SetProcessDpiAwarenessContext"));
    if (setDpi) setDpi(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (headlessRemove || headlessStart || headlessSwitch) {
        std::wstring result;
        if (headlessSwitch) {
            const std::wstring removed = RemoveProbe();
            if (removed.find(L"测试面板已移除") == std::wstring::npos &&
                    removed.find(L"目前没有测试面板") == std::wstring::npos) {
                result = removed;
            } else {
                result = removed + L"\r\n" + StartProbe();
            }
        } else {
            result = headlessRemove ? RemoveProbe() : StartProbe();
        }
        WriteSelfTestResult(result, L"headless-status.txt");
        if(openSettings&&result.find(L"微信原界面建议已启用")!=std::wstring::npos){
            Target target;std::wstring reason;
            if(SelectTarget(target,reason)){HWND panel=FindWindowExW(target.hwnd,nullptr,kProbeClass,nullptr);if(VerifyPanel(panel,target,reason)){DWORD_PTR response=0;SendMessageTimeoutW(panel,WM_COMMAND,kSettingsButton,0,SMTO_ABORTIFHUNG|SMTO_BLOCK,3000,&response);}}
        }
        if(defaultAttach && !headlessRemove && result.find(L"微信原界面建议已启用")==std::wstring::npos)
            MessageBoxW(nullptr,result.c_str(),L"talk helper 启用失败",MB_OK|MB_ICONERROR);
        return result.find(headlessRemove ? L"测试面板已移除" : L"微信原界面建议已启用")
            != std::wstring::npos ? 0 : 1;
    }
    Controller controller;
    using DpiFn = UINT (WINAPI*)();
    const auto dpiForSystem = reinterpret_cast<DpiFn>(GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForSystem"));
    if (dpiForSystem) controller.dpi = dpiForSystem();
    WNDCLASSW cls{};
    cls.hInstance = instance;
    cls.lpfnWndProc = ControllerProcedure;
    cls.lpszClassName = kControllerClass;
    cls.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    cls.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    cls.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
    if (!RegisterClassW(&cls)) return 1;
    const HWND window = CreateWindowExW(0, kControllerClass, L"talk helper · 微信内联聊天视图",
        WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, Pixels(controller, 740), Pixels(controller, 570),
        nullptr, nullptr, instance, &controller);
    if (!window) return 1;
    ShowWindow(window, showCommand);
    UpdateWindow(window);
    MSG message{};
    while (true) {
        const BOOL read = GetMessageW(&message, nullptr, 0, 0);
        if (read == -1) return 1;
        if (read == 0) return static_cast<int>(message.wParam);
        if (!IsDialogMessageW(window, &message)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
}
