#pragma once
#include <windows.h>
#include <wincrypt.h>
#include <array>
#include <string>
#include <cwchar>

// Internal Qt layouts are selected only after both files match a reviewed build.
// The fingerprint is independent of WeChat's installation directory.
namespace hostcompat {
struct Offsets {
    uintptr_t gate,platform,getter,setter;
    uintptr_t list,model,viewModel,item,rowMeta,modelHeight,margins,reload;
    uintptr_t modelIdentity,modelOther,modelField;
};
struct Build {
    const wchar_t* version;
    unsigned long long exeSize,dllSize;
    std::array<BYTE,32> exeHash,dllHash;
    Offsets offsets;
};
inline constexpr Build builds[]{
    {L"4.1.13.65",3127856ULL,198060584ULL,
     {0xCA,0x04,0xAF,0x57,0xA9,0xA3,0x1F,0x8F,0xB2,0xDA,0xF8,0xC0,0xA0,0xE9,0xA5,0xF0,
      0x39,0x0A,0x4D,0x85,0x1C,0xDE,0xC4,0xDD,0xBA,0x5F,0x9F,0x00,0x20,0xFD,0xD6,0x23},
     {0x8F,0x74,0x06,0xA8,0xA4,0x65,0xE8,0x51,0xEE,0x10,0xEA,0xEC,0xCC,0xB5,0x72,0xD0,
      0xE5,0xB4,0xE0,0x0D,0x48,0x0C,0x77,0x09,0x38,0xC7,0x14,0xC3,0x96,0x09,0x7B,0x74},
     {0x0AE2B0C8,0x0B5D5D90,0x0C83FD0,0x2765D90,
      0x8FD5DD8,0x8F0FC28,0x9329148,0x930C9B8,0x879970,0x1C0A000,0x5B05D0,0x225A170,
      0x1C0BC60,0x1C09A80,0x200}},
    {L"4.1.15.13",2939440ULL,201552944ULL,
     {0xA8,0x32,0xFB,0x32,0x1D,0xDB,0x5F,0x97,0x01,0xDD,0x3A,0x7B,0xB1,0x95,0x88,0x04,
      0xF0,0x9B,0x62,0x0B,0x9A,0xD3,0x28,0xF5,0x2E,0x2E,0x35,0x26,0x51,0xAB,0x88,0x6C},
     {0x10,0xF8,0xE9,0x95,0x45,0x3E,0x2D,0xA4,0x6D,0x4F,0x2B,0x50,0x80,0xCD,0x6D,0xA1,
      0xF1,0x3C,0xC5,0x14,0x77,0x46,0xAD,0xC1,0x19,0xCE,0xAE,0x38,0xCB,0x03,0x9D,0xE5},
     {0x0B135C38,0x0B9134B0,0x0C43EE0,0x25EACD0,
      0x920EC28,0x9180BA8,0x958A5A8,0x956D338,0x889A50,0x1C16B00,0x5B53D0,0x209DF00,
      0x1C18B30,0x1C16580,0x278}}
};

inline bool basenameIs(const std::wstring& path,const wchar_t* expected) {
    const auto cut=path.find_last_of(L"\\/");
    return _wcsicmp(path.c_str()+(cut==std::wstring::npos?0:cut+1),expected)==0;
}

inline bool matches(const std::wstring& path,unsigned long long size,const std::array<BYTE,32>& expected) {
    WIN32_FILE_ATTRIBUTE_DATA info{};
    if(!GetFileAttributesExW(path.c_str(),GetFileExInfoStandard,&info)
        ||(static_cast<unsigned long long>(info.nFileSizeHigh)<<32|info.nFileSizeLow)!=size)return false;
    HANDLE file=CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,
                            nullptr,OPEN_EXISTING,FILE_FLAG_SEQUENTIAL_SCAN,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    HCRYPTPROV provider=0;HCRYPTHASH hash=0;bool result=false;
    if(CryptAcquireContextW(&provider,nullptr,nullptr,PROV_RSA_AES,CRYPT_VERIFYCONTEXT)
       &&CryptCreateHash(provider,CALG_SHA_256,0,0,&hash)) {
        std::array<BYTE,65536> buffer{};DWORD count=0;bool good=true;
        unsigned long long total=0;
        while(true) {
            if(!ReadFile(file,buffer.data(),static_cast<DWORD>(buffer.size()),&count,nullptr)) {good=false;break;}
            if(!count)break;
            total+=count;
            if(!CryptHashData(hash,buffer.data(),count,0)){good=false;break;}
        }
        if(total!=size)good=false;
        std::array<BYTE,32> actual{};DWORD bytes=static_cast<DWORD>(actual.size());
        if(good && CryptGetHashParam(hash,HP_HASHVAL,actual.data(),&bytes,0)
           &&bytes==actual.size())result=actual==expected;
    }
    if(hash)CryptDestroyHash(hash);
    if(provider)CryptReleaseContext(provider,0);
    CloseHandle(file);
    return result;
}

inline const Build* exeBuild(const std::wstring& path) {
    if(!basenameIs(path,L"Weixin.exe"))return nullptr;
    for(const auto& build:builds)if(matches(path,build.exeSize,build.exeHash))return &build;
    return nullptr;
}
inline const Build* dllBuild(HMODULE module) {
    static HMODULE checked=nullptr;static const Build* accepted=nullptr;
    if(module==checked)return accepted;
    wchar_t path[32768]{};
    const DWORD length=GetModuleFileNameW(module,path,32768);
    accepted=nullptr;
    if(length&&length<32768&&basenameIs(path,L"Weixin.dll"))
        for(const auto& build:builds)if(matches(path,build.dllSize,build.dllHash)){accepted=&build;break;}
    checked=module;
    return accepted;
}
inline bool knownExe(const std::wstring& path){return exeBuild(path)!=nullptr;}
inline bool knownDll(HMODULE module){return dllBuild(module)!=nullptr;}
}
