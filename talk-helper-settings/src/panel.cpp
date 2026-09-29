#include "probe.h"
#include "host_compat.h"
#include "render.h"
#include <bcrypt.h>
#include <windowsx.h>
#include <memory>
#include <cstring>
#include <commctrl.h>
#include <shlwapi.h>
#include <map>
#include <deque>
#include "native_layout.h"

namespace {
HINSTANCE moduleHandle=nullptr; HMODULE retainedModule=nullptr; ULONG_PTR graphicsToken=0;
HHOOK mouseObserver=nullptr,scrollObserver=nullptr; HWND activePanel=nullptr;bool following=false;
volatile BYTE* gate=nullptr; BYTE originalGate=0; bool restoreReader=false;
void deactivate() {
    if(gate && originalGate==0 && *gate==1) *gate=0;
    gate=nullptr;
    if(restoreReader) SystemParametersInfoW(SPI_SETSCREENREADER,FALSE,nullptr,SPIF_SENDCHANGE);
    restoreReader=false;
}
bool activate() {
    HMODULE host=GetModuleHandleW(L"Weixin.dll"); if(!host) return false;
    const auto* build=hostcompat::dllBuild(host);if(!build)return false;
    const auto& offsets=build->offsets;
    auto* byte=reinterpret_cast<volatile BYTE*>(host)+offsets.gate;
    MEMORY_BASIC_INFORMATION memory{};
    if(!VirtualQuery(const_cast<BYTE*>(byte),&memory,sizeof(memory))||memory.State!=MEM_COMMIT)return false;
    const DWORD prot=memory.Protect&255;
    if((prot!=PAGE_READWRITE&&prot!=PAGE_WRITECOPY)||(*byte!=0&&*byte!=1))return false;
    // This host's Qt activation observer API must run on its UI thread. A gate
    // write alone does not initialize controls after a fresh client startup.
    const BYTE getterCode[]={0xb8,0x98,0,0,0,0x48,0x03,0x41,0x08,0xc3};
    const BYTE setterCode[]={0x88,0x51,0x08,0x89,0xd1,0xe9};
    const auto base=reinterpret_cast<uintptr_t>(host);
    auto readWord=[](uintptr_t address){uintptr_t value=0;SIZE_T done=0;return ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<void*>(address),&value,8,&done)&&done==8?value:0;};
    const auto platform=readWord(base+offsets.platform),table=readWord(platform),getter=readWord(table+0x78);
    if(!platform||getter!=base+offsets.getter||memcmp(reinterpret_cast<void*>(getter),getterCode,sizeof(getterCode))||memcmp(reinterpret_cast<void*>(base+offsets.setter),setterCode,sizeof(setterCode)))return false;
    auto accessibility=reinterpret_cast<void*(*)(void*)>(getter)(reinterpret_cast<void*>(platform));
    if(!accessibility||!VirtualQuery(accessibility,&memory,sizeof(memory))||memory.State!=MEM_COMMIT||(memory.Protect&255)!=PAGE_READWRITE)return false;
    BOOL enabled=FALSE;if(!SystemParametersInfoW(SPI_GETSCREENREADER,0,&enabled,0))return false;
    if(!enabled){if(!SystemParametersInfoW(SPI_SETSCREENREADER,TRUE,nullptr,SPIF_SENDCHANGE))return false;restoreReader=true;}
    originalGate=*byte;gate=byte;*gate=1;
    reinterpret_cast<void(*)(void*,bool)>(base+offsets.setter)(accessibility,true);
    return *gate==1;
}
struct State {
    HWND settingsWindow=nullptr;HFONT settingsFont=nullptr;SettingsPacket settingsDraft{};
    std::uint64_t settingsSequence=0;unsigned settingsCurrent=0,settingsScope=0;int settingsPage=0;bool settingsLoaded=false,settingsWaiting=false;ULONGLONG settingsSentAt=0;
    std::unique_ptr<nativeflow::Layout> flow;
    HWND parent=nullptr; BubblePacket data{};
    bool manager=false,populating=false; HWND chooser=nullptr;HFONT chooserFont=nullptr;
    std::map<std::uint64_t,HWND> cards;std::vector<DirectoryEntry> directory;
    std::deque<UINT_PTR> commandQueue,choiceQueue;std::uint64_t directorySequence=0; HANDLE worker=nullptr; DWORD workerPid=0;
    std::uint64_t token=0, sequence=0; std::uint32_t commands=0;
    bool expanded=false, stick=false, test=false; float scroll=0; UINT dpi=96;
    std::uint64_t latest=0; ULONGLONG acceptedAt=0;
    RECT followBounds{},followClip{};bool positioned=false;
    ULONGLONG maintenanceAt=0;
    FollowStats followStats{};
};
LRESULT CALLBACK procedure(HWND,UINT,WPARAM,LPARAM);
bool terminated(const wchar_t* value,size_t n){return std::find(value,value+n,L'\0')!=value+n;}
bool validRect(const std::int32_t* r){return r[0]>=0&&r[1]>=0&&r[2]>r[0]&&r[3]>r[1]&&r[2]<=32768&&r[3]<=32768;}
bool startWorker(HWND panel,State* s) {
    if(s->test)return false;
    if(s->worker){DWORD exit=0;if(GetExitCodeProcess(s->worker,&exit)&&exit==STILL_ACTIVE)return true;CloseHandle(s->worker);s->worker=nullptr;}
    wchar_t path[32768]{};DWORD n=GetModuleFileNameW(moduleHandle,path,32768);if(!n||n>=32768)return false;
    std::wstring dir(path);dir=dir.substr(0,dir.find_last_of(L"\\/")+1);
    const std::wstring executable=dir+L"TalkHelperNativeWorker-v13r2\\TalkHelperNativeWorker-v13r2.exe";
    if(GetFileAttributesW(executable.c_str())==INVALID_FILE_ATTRIBUTES)return false;
    if(BCryptGenRandom(nullptr,reinterpret_cast<PUCHAR>(&s->token),sizeof(s->token),BCRYPT_USE_SYSTEM_PREFERRED_RNG)<0||!s->token)return false;
    s->sequence=0;DWORD pid=0;GetWindowThreadProcessId(s->parent,&pid);
    std::wstring cmd=L"\""+executable+L"\" --parent "+std::to_wstring(reinterpret_cast<UINT_PTR>(s->parent))
        +L" --panel "+std::to_wstring(reinterpret_cast<UINT_PTR>(panel))+L" --parent-pid "+std::to_wstring(pid)
        +L" --token "+std::to_wstring(s->token)+L" --config \""+dir+L"config.json\"";
    std::vector<wchar_t> args(cmd.begin(),cmd.end());args.push_back(0);
    STARTUPINFOW si{};si.cb=sizeof(si);si.dwFlags=STARTF_USESHOWWINDOW;si.wShowWindow=SW_HIDE;PROCESS_INFORMATION pi{};
    if(!CreateProcessW(executable.c_str(),args.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,dir.c_str(),&si,&pi))return false;
    CloseHandle(pi.hThread);s->worker=pi.hProcess;s->workerPid=pi.dwProcessId;return true;
}
void placeBound(HWND panel,State* s,const nativefollow::Position* position) {
    if(!position||!position->visible||!*s->data.title){if(GetWindowLongPtrW(panel,GWL_STYLE)&WS_VISIBLE)ShowWindow(panel,SW_HIDE);s->positioned=false;return;}
    const auto& p=*position;const int width=p.bounds.right-p.bounds.left,height=p.bounds.bottom-p.bounds.top;
    s->dpi=GetDpiForWindow(s->parent);if(!s->dpi)s->dpi=96;
    if(s->positioned&&EqualRect(&s->followBounds,&p.bounds)&&EqualRect(&s->followClip,&p.clip)&&IsWindowVisible(panel))return;
    HRGN region=CreateRoundRectRgn(0,0,width+1,height+1,MulDiv(16,s->dpi,96),MulDiv(16,s->dpi,96));
    HRGN clip=CreateRectRgn(p.clip.left-p.bounds.left,p.clip.top-p.bounds.top,p.clip.right-p.bounds.left,p.clip.bottom-p.bounds.top);
    if(!region||!clip){if(region)DeleteObject(region);if(clip)DeleteObject(clip);ShowWindow(panel,SW_HIDE);return;}
    CombineRgn(region,region,clip,RGN_AND);DeleteObject(clip);
    if(!SetWindowRgn(panel,region,FALSE))DeleteObject(region);
    SetWindowPos(panel,HWND_TOP,p.bounds.left,p.bounds.top,width,height,SWP_NOACTIVATE|SWP_SHOWWINDOW);
    s->followBounds=p.bounds;s->followClip=p.clip;s->positioned=true;
    if(activePanel){auto* owner=reinterpret_cast<State*>(GetWindowLongPtrW(activePanel,GWLP_USERDATA));if(owner)++owner->followStats.moves;}
}
void refreshFollowing() {
    if(following||!activePanel)return;auto* owner=reinterpret_cast<State*>(GetWindowLongPtrW(activePanel,GWLP_USERDATA));
    if(!owner||!owner->flow)return;
    following=true;LARGE_INTEGER begin{},end{},frequency{};QueryPerformanceCounter(&begin);QueryPerformanceFrequency(&frequency);
    try{auto positions=owner->flow->positions(GetDpiForWindow(owner->parent));
        for(const auto& entry:owner->cards){auto* card=reinterpret_cast<State*>(GetWindowLongPtrW(entry.second,GWLP_USERDATA));
            if(!card||card->expanded)continue;
            auto found=positions.find(entry.first);placeBound(entry.second,card,found==positions.end()?nullptr:&found->second);}
        owner->followStats.visible=0;owner->followStats.retained=static_cast<uint32_t>(owner->cards.size());
        for(const auto& entry:owner->cards)if(GetWindowLongPtrW(entry.second,GWL_STYLE)&WS_VISIBLE)++owner->followStats.visible;}
    catch(...){}QueryPerformanceCounter(&end);if(frequency.QuadPart>0)owner->followStats.maxMicros=std::max(owner->followStats.maxMicros,static_cast<uint32_t>((end.QuadPart-begin.QuadPart)*1000000/frequency.QuadPart));++owner->followStats.events;following=false;
}
LRESULT CALLBACK observeScroll(int code,WPARAM wp,LPARAM lp) {
    if(code==HC_ACTION&&lp&&activePanel&&!following){const auto* call=reinterpret_cast<const CWPRETSTRUCT*>(lp);
        auto* owner=reinterpret_cast<State*>(GetWindowLongPtrW(activePanel,GWLP_USERDATA));
        bool ours=call->hwnd==activePanel;
        if(owner)for(const auto& entry:owner->cards)if(entry.second==call->hwnd){ours=true;break;}
        if(!ours&&call->message!=WM_COPYDATA&&(call->message==WM_MOUSEWHEEL||call->message==WM_MOUSEMOVE||call->message==WM_VSCROLL||call->message==WM_HSCROLL||call->message==WM_SIZE||call->message==WM_PAINT||call->message==WM_TIMER||call->message>=WM_USER))refreshFollowing();
    }
    return CallNextHookEx(nullptr,code,wp,lp);
}
void place(HWND panel,State* s) {
    if(!s->manager&&!s->expanded&&!s->test){auto* owner=activePanel?reinterpret_cast<State*>(GetWindowLongPtrW(activePanel,GWLP_USERDATA)):nullptr;
        if(owner&&owner->flow){auto positions=owner->flow->positions(GetDpiForWindow(s->parent));auto found=positions.find(s->data.cardId);
            placeBound(panel,s,found==positions.end()?nullptr:&found->second);return;}
        ShowWindow(panel,SW_HIDE);return;}
    RECT parent{};GetClientRect(s->parent,&parent);const auto* a=s->data.area;const auto* anchor=s->data.anchor;
    if(!s->acceptedAt||(!(s->data.flags&kFlagAnchored)&&!s->expanded)||!validRect(a)||(!s->expanded&&!validRect(anchor))
        ||a[2]>parent.right||a[3]>parent.bottom||anchor[2]>parent.right||anchor[3]>parent.bottom
        ){ShowWindow(panel,SW_HIDE);return;}
    s->dpi=GetDpiForWindow(s->parent);if(!s->dpi)s->dpi=96;float scale=s->dpi/96.f;
    int x=anchor[0],y=anchor[1],width=anchor[2]-x,height=anchor[3]-y;
    if(s->expanded){
        width=std::min(static_cast<int>(420*scale),a[2]-a[0]-16);
        height=std::min(static_cast<int>(560*scale),a[3]-a[1]-16);
        x=a[2]-width-8;y=a[3]-height-8;
    }
    if(width<80||height<20){ShowWindow(panel,SW_HIDE);return;}
    RECT bounds{x,y,x+width,y+height};
    if(!s->positioned||!EqualRect(&bounds,&s->followBounds)||!IsWindowVisible(panel)){
        SetWindowPos(panel,HWND_TOP,x,y,width,height,SWP_NOACTIVATE|SWP_SHOWWINDOW);
        SetWindowRgn(panel,CreateRoundRectRgn(0,0,width+1,height+1,static_cast<int>(16*scale),static_cast<int>(16*scale)),TRUE);
        s->followBounds=bounds;s->positioned=true;}
}
void dismissOutside(POINT point) {
    if(!activePanel)return;
    auto* owner=reinterpret_cast<State*>(GetWindowLongPtrW(activePanel,GWLP_USERDATA));
    if(!owner)return;
    auto close=[&](HWND panel){auto* s=reinterpret_cast<State*>(GetWindowLongPtrW(panel,GWLP_USERDATA));RECT bounds{};
        if(s&&s->expanded&&GetWindowRect(panel,&bounds)&&!PtInRect(&bounds,point)){s->expanded=false;s->scroll=0;place(panel,s);InvalidateRect(panel,nullptr,FALSE);}};
    close(activePanel);for(const auto& entry:owner->cards)close(entry.second);
}
LRESULT CALLBACK observeMouse(int code,WPARAM wp,LPARAM lp){
    if(code==HC_ACTION&&wp==WM_LBUTTONDOWN&&lp){
        try{dismissOutside(reinterpret_cast<const MOUSEHOOKSTRUCT*>(lp)->pt);}catch(...){}
    }
    return CallNextHookEx(nullptr,code,wp,lp);
}
inlineview::Layout currentLayout(HWND panel,State* s) {
    RECT r{};GetClientRect(panel,&r);HDC dc=GetDC(panel);Gdiplus::Graphics g(dc);
    float scale=s->dpi/96.f;auto result=inlineview::layout(g,s->data,r.right/scale,r.bottom/scale,s->expanded);ReleaseDC(panel,dc);return result;
}
void clampScroll(HWND panel,State* s) {
    RECT r{};GetClientRect(panel,&r);float maxScroll=std::max(0.f,currentLayout(panel,s).height-r.bottom/(s->dpi/96.f));
    s->scroll=s->stick?maxScroll:std::clamp(s->scroll,0.f,maxScroll);
}
bool accept(HWND panel,State* s,const COPYDATASTRUCT* data) {
    if(!data||data->dwData!=kBubbleData||data->cbData!=sizeof(BubblePacket)||!data->lpData)return false;
    auto candidate=std::make_unique<BubblePacket>();memcpy(candidate.get(),data->lpData,sizeof(BubblePacket));const auto& p=*candidate;
    constexpr unsigned flags=kFlagAnchored|kFlagPaused|kFlagHasReply|kFlagBusy|kFlagError|kFlagCompact|kFlagControl|kFlagChatEnabled;
    if(!s->token||p.token!=s->token||p.magic!=kBubbleMagic||p.version!=kBubbleVersion||p.sequence<=s->sequence
      ||(p.flags&~flags)||p.cardId>100000000||(p.cardId&&(p.flags&kFlagControl))||p.tension< -1||p.tension>9
      ||!terminated(p.title,128)||!terminated(p.status,256)||!terminated(p.body,4096)||!terminated(p.reply,512)||!terminated(p.assistantName,48))return false;
    if(p.flags&kFlagAnchored){
        if(!validRect(p.area)||!validRect(p.anchor))return false;
        if(!(p.flags&kFlagCompact)&&(p.anchor[0]<p.area[0]||p.anchor[1]<p.area[1]||p.anchor[2]>p.area[2]||p.anchor[3]>p.area[3]))return false;
        if((p.flags&kFlagCompact)&&p.anchor[1]<p.area[3])return false;
    }
    if(s->manager&&p.cardId){
        if(s->cards.size()>=512&&!s->cards.count(p.cardId))return false;
        HWND child=s->cards.count(p.cardId)?s->cards[p.cardId]:nullptr;
        if(!child&&!*p.title){s->sequence=p.sequence;return true;}
        if(!child){child=CreateWindowExW(WS_EX_NOPARENTNOTIFY|WS_EX_LAYERED,kCardClass,L"talk helper 消息建议",WS_CHILD|WS_CLIPSIBLINGS,0,0,1,1,s->parent,nullptr,moduleHandle,nullptr);
            if(!child)return false;SetLayeredWindowAttributes(child,0,255,LWA_ALPHA);
            auto* card=reinterpret_cast<State*>(GetWindowLongPtrW(child,GWLP_USERDATA));card->token=s->token;card->test=s->test;s->cards[p.cardId]=child;}
        auto* card=reinterpret_cast<State*>(GetWindowLongPtrW(child,GWLP_USERDATA));
        // Off-screen/partly visible UIA rows are not withdrawals. The native
        // item binding remains authoritative until the layout explicitly drops it.
        if(!*p.title&&s->flow&&s->flow->contains(p.cardId)){card->sequence=p.sequence;s->sequence=p.sequence;place(child,card);return true;}
        bool ok=accept(child,card,data);if(ok)s->sequence=p.sequence;return ok;
    }
    const auto latest=p.sequence;
    if(wcscmp(p.title,s->data.title)){
        s->expanded=false;s->scroll=0;
        if(s->manager){if(s->flow)s->flow->clear();for(auto& card:s->cards)DestroyWindow(card.second);s->cards.clear();}
    }
    s->latest=latest;s->data=p;s->sequence=p.sequence;s->acceptedAt=GetTickCount64();
    place(panel,s);clampScroll(panel,s);InvalidateRect(panel,nullptr,FALSE);return true;
}
bool copyReply(HWND panel,State* s) {
    if(!*s->data.reply||!OpenClipboard(panel))return false;
    size_t bytes=(wcslen(s->data.reply)+1)*sizeof(wchar_t);HGLOBAL mem=GlobalAlloc(GMEM_MOVEABLE,bytes);
    if(!mem){CloseClipboard();return false;}void* ptr=GlobalLock(mem);if(!ptr){GlobalFree(mem);CloseClipboard();return false;}
    memcpy(ptr,s->data.reply,bytes);GlobalUnlock(mem);bool ok=EmptyClipboard()&&SetClipboardData(CF_UNICODETEXT,mem);CloseClipboard();if(!ok)GlobalFree(mem);return ok;
}

void command(State* s,UINT code){
    auto* owner=activePanel?reinterpret_cast<State*>(GetWindowLongPtrW(activePanel,GWLP_USERDATA)):nullptr;
    const auto target=code==kCommandToggleChat?_wcstoui64(s->data.reply,nullptr,10):code==kCommandTogglePause?0:s->data.cardId;
    if(owner&&owner->commandQueue.size()<128)owner->commandQueue.push_back((target<<4)|code);
}
constexpr wchar_t kChooserClass[]=L"TalkHelper.Chat.Chooser.v13";
void fillChooser(State* owner){
    if(!owner->chooser)return;HWND list=GetDlgItem(owner->chooser,302);if(!list)return;
    const int top=ListView_GetTopIndex(list);
    wchar_t filter[128]{};GetDlgItemTextW(owner->chooser,301,filter,128);owner->populating=true;ListView_DeleteAllItems(list);
    for(const auto& item:owner->directory){
        if(*filter&&!StrStrIW(item.name,filter))continue;
        LVITEMW row{};row.mask=LVIF_TEXT|LVIF_PARAM;row.iItem=ListView_GetItemCount(list);row.pszText=const_cast<wchar_t*>(item.name);row.lParam=item.id;
        int index=ListView_InsertItem(list,&row);wchar_t person[]=L"联系人",group[]=L"群聊";
        ListView_SetItemText(list,index,1,item.group?group:person);ListView_SetCheckState(list,index,item.enabled!=0);
    }
    owner->populating=false;
    if(top>0&&top<ListView_GetItemCount(list))ListView_EnsureVisible(list,top,FALSE);
}
LRESULT CALLBACK chooserProcedure(HWND window,UINT msg,WPARAM wp,LPARAM lp){
    auto* owner=reinterpret_cast<State*>(GetWindowLongPtrW(window,GWLP_USERDATA));
    if(msg==WM_NCCREATE){owner=reinterpret_cast<State*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);SetWindowLongPtrW(window,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(owner));owner->chooser=window;}
    if(!owner)return DefWindowProcW(window,msg,wp,lp);
    switch(msg){
    case WM_CREATE:{
        CreateWindowExW(0,L"STATIC",L"勾选后，仅该聊天的对方文字会交给 DeepSeek。未选中的聊天不分析。",WS_CHILD|WS_VISIBLE,0,0,1,1,window,(HMENU)300,moduleHandle,nullptr);
        CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",L"",WS_CHILD|WS_VISIBLE|ES_AUTOHSCROLL,0,0,1,1,window,(HMENU)301,moduleHandle,nullptr);
        HWND list=CreateWindowExW(WS_EX_CLIENTEDGE,WC_LISTVIEWW,L"",WS_CHILD|WS_VISIBLE|LVS_REPORT|LVS_SHOWSELALWAYS,0,0,1,1,window,(HMENU)302,moduleHandle,nullptr);
        ListView_SetExtendedListViewStyle(list,LVS_EX_CHECKBOXES|LVS_EX_FULLROWSELECT|LVS_EX_DOUBLEBUFFER);
        LVCOLUMNW column{};column.mask=LVCF_TEXT|LVCF_WIDTH;column.cx=420;wchar_t title[]=L"已有聊天（搜索后可多选）";column.pszText=title;ListView_InsertColumn(list,0,&column);
        column.cx=100;wchar_t kind[]=L"类型";column.pszText=kind;ListView_InsertColumn(list,1,&column);
        CreateWindowExW(0,L"STATIC",L"选择会立即保存。列表没有的聊天，可先打开，再点“启用当前聊天”。",WS_CHILD|WS_VISIBLE,0,0,1,1,window,(HMENU)303,moduleHandle,nullptr);
        owner->chooserFont=CreateFontW(-MulDiv(14,GetDpiForWindow(window),96),0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,L"Microsoft YaHei UI");
        for(int i=300;i<=303;i++)SendDlgItemMessageW(window,i,WM_SETFONT,reinterpret_cast<WPARAM>(owner->chooserFont?owner->chooserFont:GetStockObject(DEFAULT_GUI_FONT)),TRUE);
        fillChooser(owner);return 0;}
    case WM_SIZE:{RECT r{};GetClientRect(window,&r);int dpi=GetDpiForWindow(window);auto px=[&](int v){return MulDiv(v,dpi?dpi:96,96);};int pad=px(16);
        MoveWindow(GetDlgItem(window,300),pad,pad,r.right-pad*2,px(48),TRUE);MoveWindow(GetDlgItem(window,301),pad,px(72),r.right-pad*2,px(32),TRUE);
        HWND list=GetDlgItem(window,302);MoveWindow(list,pad,px(116),r.right-pad*2,std::max(60L,r.bottom-px(180)),TRUE);
        ListView_SetColumnWidth(list,0,std::max(100L,r.right-pad*2-px(108)));ListView_SetColumnWidth(list,1,px(88));
        MoveWindow(GetDlgItem(window,303),pad,r.bottom-px(52),r.right-pad*2,px(40),TRUE);return 0;}
    case WM_COMMAND:if(LOWORD(wp)==301&&HIWORD(wp)==EN_CHANGE)fillChooser(owner);return 0;
    case WM_NOTIFY:{const auto* notice=reinterpret_cast<const NMHDR*>(lp);
        if(notice&&notice->idFrom==302&&notice->code==LVN_ITEMCHANGED&&!owner->populating){auto* change=reinterpret_cast<const NMLISTVIEW*>(lp);
            if((change->uChanged&LVIF_STATE)&&((change->uOldState^change->uNewState)&LVIS_STATEIMAGEMASK)){
                LVITEMW item{};item.mask=LVIF_PARAM;item.iItem=change->iItem;
                if(ListView_GetItem(notice->hwndFrom,&item)&&item.lParam>0&&owner->choiceQueue.size()<4000){bool enabled=ListView_GetCheckState(notice->hwndFrom,change->iItem)!=0;
                    owner->choiceQueue.push_back((static_cast<UINT_PTR>(item.lParam)<<1)|enabled);
                    for(auto& entry:owner->directory)if(entry.id==static_cast<unsigned>(item.lParam))entry.enabled=enabled;
                }
            }
        }return 0;}
    case WM_CLOSE:DestroyWindow(window);return 0;
    case WM_DESTROY:owner->chooser=nullptr;if(owner->chooserFont){DeleteObject(owner->chooserFont);owner->chooserFont=nullptr;}return 0;
    }return DefWindowProcW(window,msg,wp,lp);
}
void chooseChats(State* owner){
    if(owner->chooser){ShowWindow(owner->chooser,SW_SHOW);SetForegroundWindow(owner->chooser);return;}
    WNDCLASSW cls{};cls.hInstance=moduleHandle;cls.lpfnWndProc=chooserProcedure;cls.lpszClassName=kChooserClass;cls.hCursor=LoadCursorW(nullptr,IDC_ARROW);cls.hbrBackground=reinterpret_cast<HBRUSH>(COLOR_WINDOW+1);
    if(!RegisterClassW(&cls)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)return;
    RECT parent{};GetWindowRect(owner->parent,&parent);int dpi=GetDpiForWindow(owner->parent);if(!dpi)dpi=96;
    int width=std::min(MulDiv(640,dpi,96),static_cast<int>(std::max(400L,parent.right-parent.left-40)));int height=std::min(MulDiv(520,dpi,96),static_cast<int>(std::max(300L,parent.bottom-parent.top-40)));
    HWND window=CreateWindowExW(WS_EX_DLGMODALFRAME,kChooserClass,L"talk helper · 选择启用的聊天",WS_OVERLAPPED|WS_CAPTION|WS_SYSMENU|WS_THICKFRAME, parent.left+(parent.right-parent.left-width)/2,parent.top+(parent.bottom-parent.top-height)/2,width,height,owner->parent,nullptr,moduleHandle,owner);
    if(window){ShowWindow(window,SW_SHOW);SetForegroundWindow(window);}
}
bool directory(State* s,const COPYDATASTRUCT* data){
    if(!s->manager||!data||data->dwData!=kDirectoryData||!data->lpData||data->cbData<sizeof(DirectoryHeader))return false;
    DirectoryHeader h{};memcpy(&h,data->lpData,sizeof(h));
    if(h.magic!=kDirectoryData||h.version!=kBubbleVersion||h.token!=s->token||h.sequence<=s->directorySequence||h.count>3000||data->cbData!=sizeof(h)+h.count*sizeof(DirectoryEntry))return false;
    std::vector<DirectoryEntry> entries(h.count);if(h.count)memcpy(entries.data(),reinterpret_cast<const BYTE*>(data->lpData)+sizeof(h),h.count*sizeof(DirectoryEntry));
    std::map<unsigned,bool> unique;
    for(const auto& entry:entries)if(!entry.id||entry.id>1000000||entry.enabled>1||entry.group>1||!terminated(entry.name,128)||!unique.emplace(entry.id,true).second)return false;
    s->directory=std::move(entries);s->directorySequence=h.sequence;fillChooser(s);return true;
}
#include "settings_ui.h"
void menu(HWND panel,State* s,POINT point){
    auto* owner=activePanel?reinterpret_cast<State*>(GetWindowLongPtrW(activePanel,GWLP_USERDATA)):nullptr;if(!owner)return;
    HMENU menu=CreatePopupMenu();
    std::vector<std::uint64_t> shown;
    if(s->manager){AppendMenuW(menu,MF_STRING,kChooseButton,L"选择联系人或群聊…");AppendMenuW(menu,MF_STRING|(*s->data.reply?0:MF_GRAYED),kToggleChatButton,(s->data.flags&kFlagChatEnabled)?L"停用当前聊天":L"启用当前聊天");
        HMENU replies=CreatePopupMenu();unsigned i=0;
        for(const auto& card:s->cards){auto* c=reinterpret_cast<State*>(GetWindowLongPtrW(card.second,GWLP_USERDATA));if(!c||!*c->data.title)continue;
            std::wstring title(c->data.title);if(title.size()>32)title=title.substr(0,32)+L"…";AppendMenuW(replies,MF_STRING,1000+i,title.c_str());shown.push_back(card.first);i++;}
        if(i)AppendMenuW(menu,MF_POPUP,reinterpret_cast<UINT_PTR>(replies),L"分别查看本聊天的建议");else DestroyMenu(replies);
    }else{AppendMenuW(menu,MF_STRING,kCopyButton,L"复制这条建议回复");AppendMenuW(menu,MF_STRING,kRetryButton,L"重新生成这条建议");}
    AppendMenuW(menu,MF_STRING,kSettingsButton,L"设置…");AppendMenuW(menu,MF_STRING,kPauseButton,(s->data.flags&kFlagPaused)?L"继续分析":L"暂停分析");AppendMenuW(menu,MF_SEPARATOR,0,nullptr);AppendMenuW(menu,MF_STRING,kCloseButton,L"关闭 talk helper");
    UINT selected=TrackPopupMenu(menu,TPM_RETURNCMD,point.x,point.y,0,panel,nullptr);DestroyMenu(menu);
    if(selected>=1000&&selected-1000<shown.size()){
        auto found=owner->cards.find(shown[selected-1000]);
        if(found!=owner->cards.end()){auto* c=reinterpret_cast<State*>(GetWindowLongPtrW(found->second,GWLP_USERDATA));
            if(c&&*c->data.title){c->expanded=true;c->scroll=0;c->stick=false;place(found->second,c);InvalidateRect(found->second,nullptr,FALSE);}}
    }else if(selected)SendMessageW(panel,WM_COMMAND,selected,0);
}
LRESULT impl(HWND panel,UINT msg,WPARAM wp,LPARAM lp) {
    auto* s=reinterpret_cast<State*>(GetWindowLongPtrW(panel,GWLP_USERDATA));
    if(msg==WM_NCCREATE){auto* created=new(std::nothrow)State;if(!created)return FALSE;created->parent=GetParent(panel);created->data.tension=-1;SetWindowLongPtrW(panel,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(created));return TRUE;}
    if(!s)return DefWindowProcW(panel,msg,wp,lp);
    switch(msg){
    case WM_CREATE:SetTimer(panel,91,250,nullptr);return 0;
    case WM_TIMER:
        if(s->manager&&gate&&*gate==0)*gate=1;
        if(s->manager&&s->settingsWaiting&&GetTickCount64()-s->settingsSentAt>10000){s->settingsWaiting=false;SecureZeroMemory(&s->settingsDraft,sizeof(s->settingsDraft));settingsBusy(s,false);if(s->settingsWindow)SetDlgItemTextW(s->settingsWindow,413,L"保存超时，请重试；若服务已停止，请重新启用 talk helper。");}
        if(s->manager&&s->flow){if(GetTickCount64()-s->maintenanceAt>=250){s->maintenanceAt=GetTickCount64();if(s->worker&&WaitForSingleObject(s->worker,0)==WAIT_OBJECT_0)s->flow->clear();else s->flow->tick();}refreshFollowing();}
        if(s->manager){for(auto it=s->cards.begin();it!=s->cards.end();){auto* child=reinterpret_cast<State*>(GetWindowLongPtrW(it->second,GWLP_USERDATA));
            if(!child){it=s->cards.erase(it);}else if(s->flow&&!s->flow->contains(it->first)){DestroyWindow(it->second);it=s->cards.erase(it);}else ++it;}place(panel,s);}
        else if(s->expanded||s->test)place(panel,s);return 0;

    case WM_SIZE:clampScroll(panel,s);InvalidateRect(panel,nullptr,FALSE);return 0;
    case WM_ERASEBKGND:return 1;
    case WM_PAINT:{PAINTSTRUCT ps{};HDC dc=BeginPaint(panel,&ps);RECT r{};GetClientRect(panel,&r);
        HDC back=CreateCompatibleDC(dc);HBITMAP bitmap=CreateCompatibleBitmap(dc,std::max(1L,r.right),std::max(1L,r.bottom));HGDIOBJ old=SelectObject(back,bitmap);
        {Gdiplus::Graphics g(back);float scale=s->dpi/96.f;g.ScaleTransform(scale,scale);inlineview::paint(g,s->data,r.right/scale,r.bottom/scale,s->expanded,s->scroll);}
        BitBlt(dc,0,0,r.right,r.bottom,back,0,0,SRCCOPY);SelectObject(back,old);DeleteObject(bitmap);DeleteDC(back);EndPaint(panel,&ps);return 0;}
    case WM_MOUSEWHEEL:if(!s->expanded&&!s->manager){SendMessageW(s->parent,msg,wp,lp);refreshFollowing();return 0;}s->stick=false;s->scroll-=GET_WHEEL_DELTA_WPARAM(wp)/120.f*72;clampScroll(panel,s);InvalidateRect(panel,nullptr,FALSE);return 0;
    case WM_LBUTTONUP:{if(s->manager&&(s->data.flags&kFlagControl)){chooseChats(s);return 0;}float scale=s->dpi/96.f;float x=GET_X_LPARAM(lp)/scale,y=GET_Y_LPARAM(lp)/scale;
        if(!s->expanded&&(s->data.flags&kFlagCompact)){s->expanded=true;s->scroll=0;place(panel,s);InvalidateRect(panel,nullptr,FALSE);return 0;}
        for(const auto& i:currentLayout(panel,s).items){if(inlineview::contains(i.detail,x,y)){s->expanded=!s->expanded;s->scroll=0;place(panel,s);clampScroll(panel,s);InvalidateRect(panel,nullptr,FALSE);return 0;}
            if(inlineview::contains(i.copy,x,y)){copyReply(panel,s);return 0;}if(inlineview::contains(i.next,x,y)){command(s,kCommandNextReply);return 0;}}return 0;}
    case WM_CONTEXTMENU:{POINT p{GET_X_LPARAM(lp),GET_Y_LPARAM(lp)};if(p.x==-1)GetCursorPos(&p);menu(panel,s,p);return 0;}
    case WM_COMMAND:switch(LOWORD(wp)){
        case kSettingsButton:{auto* owner=activePanel?reinterpret_cast<State*>(GetWindowLongPtrW(activePanel,GWLP_USERDATA)):nullptr;if(owner)chooseSettings(owner);break;}
        case kChooseButton:chooseChats(s);break;case kToggleChatButton:command(s,kCommandToggleChat);break;
        case kCloseButton:if(activePanel)DestroyWindow(activePanel);break;case kCopyButton:copyReply(panel,s);break;
        case kRetryButton:command(s,kCommandRetry);break;case kNextButton:command(s,kCommandNextReply);break;
        case kPauseButton:command(s,kCommandTogglePause);break;
        case kExpandButton:s->expanded=!s->expanded;s->scroll=0;place(panel,s);clampScroll(panel,s);InvalidateRect(panel,nullptr,FALSE);break;}return 0;
    case WM_MOUSEACTIVATE:return MA_NOACTIVATE;
    case WM_COPYDATA:{const auto* data=reinterpret_cast<const COPYDATASTRUCT*>(lp);
        if(data&&data->dwData==kSettingsData)return acceptSettings(s,data);
        if(data&&data->dwData==nativeflow::dataId&&s->manager){if(!s->flow)s->flow=std::make_unique<nativeflow::Layout>(s->parent);return s->flow->accept(data,s->token);}
        return data&&data->dwData==kDirectoryData?directory(s,data):accept(panel,s,data);}
    case kQueryProof:return kProofValue;
    case kQueryCardId:return static_cast<LRESULT>(s->data.cardId);
    case kQuerySettingsDraft:return s->manager&&s->settingsWaiting&&static_cast<std::uint64_t>(wp)==s->token&&!lp?reinterpret_cast<LRESULT>(&s->settingsDraft):0;
    case kQueryFollowing:return s->manager&&static_cast<std::uint64_t>(wp)==s->token&&!lp?reinterpret_cast<LRESULT>(&s->followStats):0;
    case kStartWorker:return !wp&&!lp&&startWorker(panel,s)?1:0;
    case kPollCommands:if(static_cast<std::uint64_t>(wp)!=s->token||lp||!s->manager)return 0;{if(s->commandQueue.empty())return 0;auto result=s->commandQueue.front();s->commandQueue.pop_front();return result;}
    case kPollChoices:if(static_cast<std::uint64_t>(wp)!=s->token||lp||!s->manager)return 0;{if(s->choiceQueue.empty())return 0;auto result=s->choiceQueue.front();s->choiceQueue.pop_front();return result;}
    case WM_CLOSE:DestroyWindow(panel);return 0;
    case WM_DESTROY:KillTimer(panel,91);if(s->manager){if(s->settingsWindow)DestroyWindow(s->settingsWindow);if(s->chooser)DestroyWindow(s->chooser);for(auto& card:s->cards)DestroyWindow(card.second);s->cards.clear();}if(activePanel==panel){activePanel=nullptr;if(mouseObserver)UnhookWindowsHookEx(mouseObserver);mouseObserver=nullptr;if(scrollObserver)UnhookWindowsHookEx(scrollObserver);scrollObserver=nullptr;}if(s->worker)CloseHandle(s->worker);s->worker=nullptr;if(s->manager)deactivate();SecureZeroMemory(&s->settingsDraft,sizeof(s->settingsDraft));return 0;
    case WM_NCDESTROY:SetWindowLongPtrW(panel,GWLP_USERDATA,0);delete s;return DefWindowProcW(panel,msg,wp,lp);
    }return DefWindowProcW(panel,msg,wp,lp);
}
LRESULT CALLBACK procedure(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp){try{return impl(hwnd,msg,wp,lp);}catch(...){return msg==WM_COPYDATA||msg==kStartWorker?0:DefWindowProcW(hwnd,msg,wp,lp);}}
bool isolatedCaller(){wchar_t path[32768]{};GetModuleFileNameW(nullptr,path,32768);const wchar_t* name=wcsrchr(path,L'\\');return name&&!_wcsicmp(name+1,L"TalkHelper-Native-v13.exe");}
}
extern "C" __declspec(dllexport) HWND WINAPI TalkHelperProbeStart(HWND parent) {
    DWORD pid=0;if(GetWindowThreadProcessId(parent,&pid)!=GetCurrentThreadId()||pid!=GetCurrentProcessId())return nullptr;
    if(HWND old=FindWindowExW(parent,nullptr,kProbeClass,nullptr))return old;
    if(!retainedModule&&!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,reinterpret_cast<LPCWSTR>(&TalkHelperProbeStart),&retainedModule))return nullptr;
    if(!graphicsToken){Gdiplus::GdiplusStartupInput input;if(Gdiplus::GdiplusStartup(&graphicsToken,&input,nullptr)!=Gdiplus::Ok)return nullptr;}
    if(!isolatedCaller()&&!activate())return nullptr;
    WNDCLASSEXW cls{};cls.cbSize=sizeof(cls);cls.hInstance=moduleHandle;cls.lpfnWndProc=procedure;cls.lpszClassName=kProbeClass;cls.hCursor=LoadCursorW(nullptr,IDC_ARROW);
    if(!RegisterClassExW(&cls)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS){deactivate();return nullptr;}
    cls.lpszClassName=kCardClass;if(!RegisterClassExW(&cls)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS){deactivate();return nullptr;}
    HWND child=CreateWindowExW(WS_EX_NOPARENTNOTIFY|WS_EX_LAYERED,kProbeClass,L"talk helper 微信建议卡",WS_CHILD|WS_CLIPSIBLINGS,0,0,720,540,parent,nullptr,moduleHandle,nullptr);
    if(child&&!SetLayeredWindowAttributes(child,0,255,LWA_ALPHA)){DestroyWindow(child);child=nullptr;}
    if(child){auto* owner=reinterpret_cast<State*>(GetWindowLongPtrW(child,GWLP_USERDATA));owner->manager=true;SetTimer(child,91,16,nullptr);INITCOMMONCONTROLSEX common{sizeof(common),ICC_LISTVIEW_CLASSES};InitCommonControlsEx(&common);activePanel=child;mouseObserver=SetWindowsHookExW(WH_MOUSE,observeMouse,moduleHandle,GetCurrentThreadId());scrollObserver=SetWindowsHookExW(WH_CALLWNDPROCRET,observeScroll,moduleHandle,GetCurrentThreadId());if(!mouseObserver||!scrollObserver){DestroyWindow(child);child=nullptr;}}
    if(!child)deactivate();
    return child;
}
extern "C" __declspec(dllexport) BOOL WINAPI TalkHelperTestSession(HWND panel,std::uint64_t token){
    if(!isolatedCaller()||!token||GetWindowThreadProcessId(panel,nullptr)!=GetCurrentThreadId())return FALSE;
    auto* s=reinterpret_cast<State*>(GetWindowLongPtrW(panel,GWLP_USERDATA));if(!s||s->worker)return FALSE;s->token=token;s->test=true;return TRUE;
}
extern "C" __declspec(dllexport) BOOL WINAPI TalkHelperRenderReference(const wchar_t* path){return isolatedCaller()&&graphicsToken&&inlineview::saveReference(path);}
extern "C" __declspec(dllexport) BOOL WINAPI TalkHelperTestOutsideClick(HWND panel){
    auto* s=reinterpret_cast<State*>(GetWindowLongPtrW(panel,GWLP_USERDATA));
    if(!isolatedCaller()||panel!=activePanel||!s||!s->test)return FALSE;
    SendMessageW(panel,WM_COMMAND,kExpandButton,0);if(!s->expanded)return FALSE;
    RECT bounds{};if(!GetWindowRect(panel,&bounds))return FALSE;
    MOUSEHOOKSTRUCT click{};click.pt={bounds.left-1,bounds.top};observeMouse(HC_ACTION,WM_LBUTTONDOWN,reinterpret_cast<LPARAM>(&click));
    return !s->expanded;
}
extern "C" __declspec(dllexport) BOOL WINAPI TalkHelperTestFollowing(HWND panel){
    auto* owner=reinterpret_cast<State*>(GetWindowLongPtrW(panel,GWLP_USERDATA));
    if(!isolatedCaller()||panel!=activePanel||!owner||!owner->test||owner->cards.empty()){SetLastError(9001);return 0;}
    const HWND child=owner->cards.begin()->second;auto* s=reinterpret_cast<State*>(GetWindowLongPtrW(child,GWLP_USERDATA));
    RECT area{300,90,1200,600},row{300,100,1200,319};auto first=nativefollow::project(area,row,142,96);
    if(!first.visible||first.bounds.top!=183||first.bounds.left!=368||first.bounds.bottom!=284){SetLastError(9002);return 0;}
    placeBound(child,s,&first);RECT actual{};GetWindowRect(child,&actual);MapWindowPoints(nullptr,owner->parent,reinterpret_cast<POINT*>(&actual),2);
    if(!EqualRect(&actual,&first.bounds)){SetLastError(9003);return 0;}
    OffsetRect(&row,0,-150);auto moved=nativefollow::project(area,row,142,96);placeBound(child,s,&moved);
    if(!moved.visible||moved.bounds.top!=33||moved.clip.top!=90){SetLastError(9004);return 0;}
    HRGN region=CreateRectRgn(0,0,0,0);RECT regionBounds{};GetWindowRgn(child,region);GetRgnBox(region,&regionBounds);DeleteObject(region);
    if(regionBounds.top!=57){SetLastError(9005);return 0;}
    RECT bottomRow{300,490,1200,709};auto bottom=nativefollow::project(area,bottomRow,142,96);
    if(!bottom.visible||bottom.clip.bottom!=600||bottom.bounds.bottom!=674){SetLastError(9006);return 0;}
    RECT offscreen{300,800,1200,1019};auto hidden=nativefollow::project(area,offscreen,142,96);placeBound(child,s,&hidden);
    if(hidden.visible||(GetWindowLongPtrW(child,GWL_STYLE)&WS_VISIBLE)){SetLastError(9007);return 0;}
    placeBound(child,s,&first);if(!(GetWindowLongPtrW(child,GWL_STYLE)&WS_VISIBLE)||!s->positioned){SetLastError(9008);return 0;}
    RECT scaledArea{450,135,1800,900},scaledRow{450,150,1800,478};auto scaled=nativefollow::project(scaledArea,scaledRow,142,144);
    if(!scaled.visible||scaled.bounds.left!=552||scaled.bounds.top!=274||scaled.bounds.bottom!=426){SetLastError(9009);return 0;}
    RECT tallRow{300,100,1200,471};auto tall=nativefollow::project(area,tallRow,294,96);
    if(!tall.visible||tall.bounds.left!=368||tall.bounds.top!=183||tall.bounds.bottom!=435){SetLastError(9013);return 0;}
    OffsetRect(&tallRow,0,-150);auto tallMoved=nativefollow::project(area,tallRow,294,96);
    if(!tallMoved.visible||tallMoved.bounds.top!=33||tallMoved.clip.top!=90){SetLastError(9014);return 0;}
    RECT tallBottom{300,420,1200,791};auto tallClipped=nativefollow::project(area,tallBottom,294,96);
    if(!tallClipped.visible||tallClipped.clip.bottom!=600||tallClipped.bounds.bottom!=755){SetLastError(9015);return 0;}
    RECT tallScaledRow{450,150,1800,706};auto tallScaled=nativefollow::project(scaledArea,tallScaledRow,294,144);
    if(!tallScaled.visible||tallScaled.bounds.top!=274||tallScaled.bounds.bottom!=652){SetLastError(9016);return 0;}
    if(nativefollow::project(area,row,0,96).visible){SetLastError(9010);return 0;}
    if(SendMessageW(panel,kQueryFollowing,owner->token+1,0)){SetLastError(9011);return 0;}
    auto* stats=reinterpret_cast<FollowStats*>(SendMessageW(panel,kQueryFollowing,owner->token,0));
    if(!stats||stats->size!=32||stats->mode!=1||stats->moves<3){SetLastError(9012);return 0;}
    return TRUE;
}
extern "C" __declspec(dllexport) LRESULT CALLBACK TalkHelperProbeHookProc(int code,WPARAM wp,LPARAM lp){
    if(code>=0&&lp){const auto* call=reinterpret_cast<const CWPSTRUCT*>(lp);UINT msg=RegisterWindowMessageW(kControlMessage);if(msg&&call->message==msg&&call->wParam==kStartCommand&&!call->lParam)TalkHelperProbeStart(call->hwnd);}return CallNextHookEx(nullptr,code,wp,lp);
}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID){if(reason==DLL_PROCESS_ATTACH)moduleHandle=instance;return TRUE;}
