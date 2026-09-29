#pragma once
#ifndef UNICODE
#define UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <cstdint>

#ifdef TALKHELPER_REMOVE_LEGACY
inline constexpr wchar_t kProbeClass[] = L"TalkHelper.Inline.Card.v13";
#else
inline constexpr wchar_t kProbeClass[] = L"TalkHelper.Inline.Card.v13r2";
#endif
inline constexpr wchar_t kCardClass[] = L"TalkHelper.Inline.CardItem.v13r2";
inline constexpr wchar_t kControlMessage[] = L"TalkHelper.Inline.Start.v13r2";
inline constexpr wchar_t kDllName[] = L"TalkHelperNative-v13r2.dll";
inline constexpr WPARAM kStartCommand = 0x54485031;
inline constexpr UINT kQueryProof = WM_APP + 17;
inline constexpr LRESULT kProofValue = 0x54485031;
inline constexpr UINT kStartWorker = WM_APP + 18;
inline constexpr UINT kPollCommands = WM_APP + 19;
inline constexpr UINT kCaptureVisibility = WM_APP + 20;
inline constexpr ULONG_PTR kBubbleData = 0x54484241;
inline constexpr std::uint32_t kBubbleMagic = 0x54484241;
inline constexpr std::uint32_t kBubbleVersion = 13;
inline constexpr ULONG_PTR kDirectoryData = 0x54484311;
inline constexpr UINT kPollChoices = WM_APP + 21;
inline constexpr UINT kQueryCardId = WM_APP + 22;
inline constexpr std::uint32_t kFlagAnchored = 1;
inline constexpr std::uint32_t kFlagPaused = 2;
inline constexpr std::uint32_t kFlagHasReply = 4;
inline constexpr std::uint32_t kFlagBusy = 8;
inline constexpr std::uint32_t kFlagError = 16;
inline constexpr std::uint32_t kFlagCompact = 32;
inline constexpr std::uint32_t kFlagControl = 64;
inline constexpr std::uint32_t kFlagChatEnabled = 128;
inline constexpr std::uint32_t kCommandToggleChat = 8;
inline constexpr std::uint32_t kCommandRetry = 1;
inline constexpr std::uint32_t kCommandNextReply = 2;
inline constexpr std::uint32_t kCommandTogglePause = 4;
inline constexpr int kCopyButton = 201;
inline constexpr int kCloseButton = 202;
inline constexpr int kNextButton = 203;
inline constexpr int kRetryButton = 204;
inline constexpr int kPauseButton = 205;
inline constexpr int kExpandButton = 206;
inline constexpr int kBodyEdit = 207;
inline constexpr int kChooseButton = 208;
inline constexpr int kToggleChatButton = 209;
inline constexpr int kSettingsButton = 210;
inline constexpr UINT kQuerySettingsDraft = WM_APP + 23;
inline constexpr UINT kQueryFollowing = WM_APP + 24;
struct FollowStats {uint32_t size=32,mode=1,events=0,moves=0,visible=0,retained=0,maxMicros=0,reserved=0;};
inline constexpr ULONG_PTR kSettingsData = 0x54485313;

#pragma pack(push, 1)
struct BubblePacket {
    std::uint32_t magic, version;
    std::uint64_t token, sequence;
    std::uint32_t flags;
    std::int32_t anchor[4], area[4];
    wchar_t title[128], status[256], body[4096], reply[512];
    std::int32_t tension;
    std::uint64_t cardId;
    wchar_t assistantName[48];
};
struct DirectoryHeader {std::uint32_t magic,version;std::uint64_t token,sequence;std::uint32_t count;};
struct DirectoryEntry {std::uint32_t id,enabled,group;wchar_t name[128];};
struct SettingsPacket {
    std::uint32_t magic,version;std::uint64_t token,sequence;
    std::uint32_t scope,context,thinking,keyPresent,flags;
    wchar_t assistant[48],base[256],model[128],relationship[128],style[1024],phrases[1024],key[256],status[256];
    wchar_t selfMbti[16],selfRating[4],selfStrengths[256],selfChallenges[256],otherAlias[64],otherMbti[16],otherRating[4];
    wchar_t stage[128],metContext[256],knownDuration[128],recentEvents[768],contactPattern[512],goal[128],feeling[256];
};
#pragma pack(pop)
static_assert(sizeof(void*) == 8, "The verified WeChat host and IPC require x64.");
static_assert(sizeof(wchar_t) == 2, "IPC uses UTF-16 code units.");
static_assert(sizeof(BubblePacket) == 10152, "IPC contract changed.");
static_assert(sizeof(SettingsPacket) == 11868, "Settings contract changed.");
static_assert(sizeof(DirectoryHeader) == 28 && sizeof(DirectoryEntry) == 268, "Directory contract changed.");

using ProbeStart = HWND (WINAPI*)(HWND);
using ProbeTestSession = BOOL (WINAPI*)(HWND, std::uint64_t);

// The loader installs WH_CALLWNDPROC on one verified Weixin UI thread and
// removes it immediately after creation. The native UI lives in WeChat; the
// hidden worker reads text directly and contacts only the official DeepSeek API.
