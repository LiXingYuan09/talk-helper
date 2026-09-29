#pragma once
constexpr wchar_t kSettingsClass[]=L"TalkHelper.Settings.v13r2";
void settingsBusy(State* s,bool busy){if(!s->settingsWindow)return;
    for(int id=401;id<=411;++id)EnableWindow(GetDlgItem(s->settingsWindow,id),!busy&&(id!=405||s->settingsCurrent));
    for(int id=430;id<=432;++id)EnableWindow(GetDlgItem(s->settingsWindow,id),!busy&&(id==430||s->settingsScope));
    for(int id=450;id<=457;++id)EnableWindow(GetDlgItem(s->settingsWindow,id),!busy&&s->settingsScope);
    for(int id=470;id<=475;++id)EnableWindow(GetDlgItem(s->settingsWindow,id),!busy&&s->settingsScope);
}
void showSettingsPage(State* s){if(!s->settingsWindow)return;HWND w=s->settingsWindow;
    if(!s->settingsScope)s->settingsPage=0;
    for(int id=401;id<=410;++id)if(GetDlgItem(w,id))ShowWindow(GetDlgItem(w,id),s->settingsPage==0?SW_SHOW:SW_HIDE);
    for(int id=414;id<=428;++id)if(GetDlgItem(w,id))ShowWindow(GetDlgItem(w,id),s->settingsPage==0?SW_SHOW:SW_HIDE);
    for(int id=439;id<=448;++id)if(GetDlgItem(w,id))ShowWindow(GetDlgItem(w,id),s->settingsPage==1?SW_SHOW:SW_HIDE);
    for(int id=450;id<=457;++id)ShowWindow(GetDlgItem(w,id),s->settingsPage==1?SW_SHOW:SW_HIDE);
    for(int id=460;id<=465;++id)ShowWindow(GetDlgItem(w,id),s->settingsPage==2?SW_SHOW:SW_HIDE);
    for(int id=470;id<=475;++id)ShowWindow(GetDlgItem(w,id),s->settingsPage==2?SW_SHOW:SW_HIDE);
    CheckRadioButton(w,430,432,430+s->settingsPage);
}
void requestSettings(State* s,unsigned scope){
    s->settingsScope=scope;s->settingsLoaded=false;if(!scope)s->settingsPage=0;showSettingsPage(s);settingsBusy(s,true);
    SetDlgItemTextW(s->settingsWindow,413,L"正在读取设置…");
    if(s->commandQueue.size()<128)s->commandQueue.push_back((static_cast<UINT_PTR>(scope)<<4)|5);
}
LRESULT CALLBACK settingsKey(HWND child,UINT msg,WPARAM wp,LPARAM lp,UINT_PTR,DWORD_PTR form){
    if(msg==WM_KEYDOWN&&wp==VK_TAB){HWND next=GetNextDlgTabItem(reinterpret_cast<HWND>(form),GetFocus(),GetKeyState(VK_SHIFT)<0);if(next)SetFocus(next);return 0;}
    if(msg==WM_KEYDOWN&&wp==VK_ESCAPE){SendMessageW(reinterpret_cast<HWND>(form),WM_CLOSE,0,0);return 0;}
    if(msg==WM_GETDLGCODE)return DefSubclassProc(child,msg,wp,lp)|DLGC_WANTTAB;
    return DefSubclassProc(child,msg,wp,lp);
}
void arrangeSettings(HWND window){
    int dpi=GetDpiForWindow(window);auto px=[&](int v){return MulDiv(v,dpi?dpi:96,96);};
    RECT r{};GetClientRect(window,&r);int width=r.right/((dpi?dpi:96)/96.f);
    auto put=[&](int id,int x,int y,int w,int h){MoveWindow(GetDlgItem(window,id),px(x),px(y),px(w),px(h),TRUE);};
    const int tabWidth=(width-40)/3;for(int i=0;i<3;++i)put(430+i,20+i*tabWidth,12,tabWidth-4,34);
    put(420,20,54,width-40,26);
    const int labels[]={421,422,423,424};for(int i=0;i<4;++i){put(labels[i],20,88+i*40,120,26);put(401+i,152,82+i*40,width-172,32);}
    put(414,152,245,width-172,26);put(405,20,274,width-40,30);
    put(425,20,318,120,26);put(406,152,310,width-172,210);
    put(426,20,379,width-40,26);put(407,20,405,width-40,70);
    put(427,20,485,width-40,26);put(408,20,510,width-40,62);
    put(428,20,588,120,26);put(409,152,580,64,34);put(410,244,580,width-264,34);
    put(439,20,57,width-40,28);
    const int leftLabels[]={440,441,442,443};const int leftFields[]={450,451,452,453};const int leftY[]={91,160,228,344};
    for(int i=0;i<4;++i){put(leftLabels[i],20,leftY[i],(width-60)/2,24);put(leftFields[i],20,leftY[i]+26,(width-60)/2,i>=2?78:32);}
    const int rightLabels[]={444,445,446,447};const int rightFields[]={454,455,456,457};const int rightY[]={91,160,228,300};
    for(int i=0;i<4;++i){put(rightLabels[i],width/2+10,rightY[i],(width-60)/2,24);put(rightFields[i],width/2+10,rightY[i]+26,(width-60)/2,i==3?68:32);}
    put(448,20,485,width-40,62);
    const int eventLabels[]={460,461,462,463,464,465};const int eventFields[]={470,471,472,473,474,475};
    const int eventY[]={75,145,210,320,430,505};const int eventH[]={34,32,82,82,50,65};
    for(int i=0;i<6;++i){put(eventLabels[i],20,eventY[i],width-40,25);put(eventFields[i],20,eventY[i]+25,width-40,eventH[i]);}
    put(413,20,620,width-40,44);put(411,width-266,672,148,36);put(412,width-104,672,84,36);
}
LRESULT CALLBACK settingsProcedure(HWND window,UINT msg,WPARAM wp,LPARAM lp){
    auto* s=reinterpret_cast<State*>(GetWindowLongPtrW(window,GWLP_USERDATA));
    if(msg==WM_NCCREATE){s=reinterpret_cast<State*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);SetWindowLongPtrW(window,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(s));s->settingsWindow=window;}
    if(!s)return DefWindowProcW(window,msg,wp,lp);
    switch(msg){
    case WM_CREATE:{
        auto label=[&](int id,const wchar_t* title){return CreateWindowExW(0,L"STATIC",title,WS_CHILD|WS_VISIBLE,0,0,1,1,window,(HMENU)(INT_PTR)id,moduleHandle,nullptr);};
        auto edit=[&](int id,int limit,bool multiline=false){DWORD style=WS_CHILD|WS_VISIBLE|WS_TABSTOP|(multiline?ES_MULTILINE|ES_AUTOVSCROLL|ES_WANTRETURN|WS_VSCROLL:ES_AUTOHSCROLL);
            HWND child=CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",L"",style,0,0,1,1,window,(HMENU)(INT_PTR)id,moduleHandle,nullptr);SendMessageW(child,EM_SETLIMITTEXT,limit,0);};
        for(int id=430;id<=432;++id)CreateWindowExW(0,L"BUTTON",id==430?L"连接与聊天":id==431?L"双方档案":L"经过与目标",WS_CHILD|WS_VISIBLE|WS_TABSTOP|BS_AUTORADIOBUTTON|BS_PUSHLIKE|(id==430?WS_GROUP:0),0,0,1,1,window,(HMENU)(INT_PTR)id,moduleHandle,nullptr);
        label(420,L"DeepSeek 连接与助手（所有聊天共用）");label(421,L"助手显示名称");label(422,L"AI 模型名称");label(423,L"API Base URL");label(424,L"API Key");
        label(414,L"留空保留现有 Key；新 Key 存入 Windows 凭据。");label(425,L"聊天对象身份");label(426,L"聊天 / 回复风格（可自由描述）");label(427,L"常用语（每行一句，合适时自然使用）");label(428,L"上下文条数");label(413,L"正在读取设置…");
        const int limits[]={47,127,255,255};for(int i=0;i<4;++i){HWND edit=CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",L"",WS_CHILD|WS_VISIBLE|WS_TABSTOP|ES_AUTOHSCROLL|(i==3?ES_PASSWORD:0),0,0,1,1,window,(HMENU)(INT_PTR)(401+i),moduleHandle,nullptr);SendMessageW(edit,EM_SETLIMITTEXT,limits[i],0);}
        CreateWindowExW(0,L"BUTTON",L"只应用到当前聊天：身份、风格、常用语与上下文",WS_CHILD|WS_VISIBLE|WS_TABSTOP|BS_AUTOCHECKBOX,0,0,1,1,window,(HMENU)405,moduleHandle,nullptr);
        HWND relation=CreateWindowExW(0,L"COMBOBOX",L"",WS_CHILD|WS_VISIBLE|WS_TABSTOP|CBS_DROPDOWN|CBS_AUTOHSCROLL|WS_VSCROLL,0,0,1,1,window,(HMENU)406,moduleHandle,nullptr);
        for(const auto* value:{L"恋人",L"朋友",L"家人",L"同事",L"客户",L"同学",L"陌生人",L"群聊"})SendMessageW(relation,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(value));SendMessageW(relation,CB_LIMITTEXT,127,0);
        for(int id:{407,408}){HWND edit=CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",L"",WS_CHILD|WS_VISIBLE|WS_TABSTOP|ES_MULTILINE|ES_AUTOVSCROLL|ES_WANTRETURN|WS_VSCROLL,0,0,1,1,window,(HMENU)(INT_PTR)id,moduleHandle,nullptr);SendMessageW(edit,EM_SETLIMITTEXT,1023,0);}
        CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",L"12",WS_CHILD|WS_VISIBLE|WS_TABSTOP|ES_NUMBER|ES_AUTOHSCROLL,0,0,1,1,window,(HMENU)409,moduleHandle,nullptr);SendDlgItemMessageW(window,409,EM_SETLIMITTEXT,2,0);
        CreateWindowExW(0,L"BUTTON",L"启用 DeepSeek 思考模式",WS_CHILD|WS_VISIBLE|WS_TABSTOP|BS_AUTOCHECKBOX,0,0,1,1,window,(HMENU)410,moduleHandle,nullptr);
        CreateWindowExW(0,L"BUTTON",L"保存并应用",WS_CHILD|WS_VISIBLE|WS_TABSTOP|BS_DEFPUSHBUTTON,0,0,1,1,window,(HMENU)411,moduleHandle,nullptr);
        CreateWindowExW(0,L"BUTTON",L"取消",WS_CHILD|WS_VISIBLE|WS_TABSTOP,0,0,1,1,window,(HMENU)412,moduleHandle,nullptr);
        label(439,L"当前聊天专属 · 主观资料（不确定可留空）");
        label(440,L"我的 MBTI");label(441,L"我的主观评分 0–100");label(442,L"我的主要优势");label(443,L"我的短板 / 在意处");
        label(444,L"对方代号 / 备注");label(445,L"对方 MBTI");label(446,L"对方主观评分 0–100");label(447,L"当前关系阶段");
        label(448,L"评分只是你当下的主观感受，不代表人的价值或成功率。MBTI 填四字母即可；未知请留空，建议会优先看真实聊天行为。");
        edit(450,15);edit(451,3);edit(452,255,true);edit(453,255,true);edit(454,63);edit(455,15);edit(456,3);edit(457,127,true);
        label(460,L"怎么认识 / 相识背景");label(461,L"认识或发展了多久");label(462,L"最近三件关键事（只填你确实知道的）");
        label(463,L"联系频率与双方投入（可写不确定）");label(464,L"当前目标：推进、确认、修复、保持或退出");label(465,L"眼下最在意的点 / 情绪强度（可选）");
        edit(470,255,true);edit(471,127);edit(472,767,true);edit(473,511,true);edit(474,127,true);edit(475,255,true);
        s->settingsFont=CreateFontW(-MulDiv(14,GetDpiForWindow(window),96),0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,L"Microsoft YaHei UI");
        for(int id=401;id<=475;++id){HWND child=GetDlgItem(window,id);if(child){SendMessageW(child,WM_SETFONT,reinterpret_cast<WPARAM>(s->settingsFont?s->settingsFont:GetStockObject(DEFAULT_GUI_FONT)),TRUE);SetWindowSubclass(child,settingsKey,1,reinterpret_cast<DWORD_PTR>(window));}}
        SendDlgItemMessageW(window,405,BM_SETCHECK,s->settingsCurrent?BST_CHECKED:BST_UNCHECKED,0);EnableWindow(GetDlgItem(window,405),s->settingsCurrent!=0);EnableWindow(GetDlgItem(window,411),FALSE);showSettingsPage(s);return 0;}
    case WM_SIZE:arrangeSettings(window);return 0;
    case WM_COMMAND:
        if(LOWORD(wp)==412){DestroyWindow(window);return 0;}
        if(LOWORD(wp)>=430&&LOWORD(wp)<=432&&HIWORD(wp)==BN_CLICKED){if(LOWORD(wp)==430||s->settingsScope)s->settingsPage=LOWORD(wp)-430;showSettingsPage(s);return 0;}
        if(LOWORD(wp)==405&&HIWORD(wp)==BN_CLICKED&&!s->settingsWaiting){requestSettings(s,SendDlgItemMessageW(window,405,BM_GETCHECK,0,0)==BST_CHECKED?s->settingsCurrent:0);return 0;}
        if(LOWORD(wp)==411&&s->settingsLoaded&&!s->settingsWaiting){
            auto& p=s->settingsDraft;SecureZeroMemory(&p,sizeof(p));p.magic=kSettingsData;p.version=kBubbleVersion;p.token=s->token;p.scope=s->settingsScope;
            GetDlgItemTextW(window,401,p.assistant,48);GetDlgItemTextW(window,402,p.model,128);GetDlgItemTextW(window,403,p.base,256);GetDlgItemTextW(window,404,p.key,256);
            GetDlgItemTextW(window,406,p.relationship,128);GetDlgItemTextW(window,407,p.style,1024);GetDlgItemTextW(window,408,p.phrases,1024);
            GetDlgItemTextW(window,450,p.selfMbti,16);GetDlgItemTextW(window,451,p.selfRating,4);GetDlgItemTextW(window,452,p.selfStrengths,256);GetDlgItemTextW(window,453,p.selfChallenges,256);
            GetDlgItemTextW(window,454,p.otherAlias,64);GetDlgItemTextW(window,455,p.otherMbti,16);GetDlgItemTextW(window,456,p.otherRating,4);GetDlgItemTextW(window,457,p.stage,128);
            GetDlgItemTextW(window,470,p.metContext,256);GetDlgItemTextW(window,471,p.knownDuration,128);GetDlgItemTextW(window,472,p.recentEvents,768);
            GetDlgItemTextW(window,473,p.contactPattern,512);GetDlgItemTextW(window,474,p.goal,128);GetDlgItemTextW(window,475,p.feeling,256);
            BOOL valid=FALSE;p.context=GetDlgItemInt(window,409,&valid,FALSE);p.thinking=SendDlgItemMessageW(window,410,BM_GETCHECK,0,0)==BST_CHECKED;
            if(!valid||p.context<3||p.context>30){SecureZeroMemory(&p,sizeof(p));SetDlgItemTextW(window,413,L"上下文条数请填写 3～30。");SetFocus(GetDlgItem(window,409));return 0;}
            s->settingsWaiting=true;s->settingsSentAt=GetTickCount64();settingsBusy(s,true);SetDlgItemTextW(window,413,L"正在保存并应用…");
            if(s->commandQueue.size()<128)s->commandQueue.push_back(6);return 0;
        }break;
    case WM_CLOSE:DestroyWindow(window);return 0;
    case WM_DESTROY:SetDlgItemTextW(window,404,L"");s->settingsWindow=nullptr;s->settingsLoaded=false;s->settingsWaiting=false;SecureZeroMemory(&s->settingsDraft,sizeof(s->settingsDraft));if(s->settingsFont){DeleteObject(s->settingsFont);s->settingsFont=nullptr;}return 0;
    }
    return DefWindowProcW(window,msg,wp,lp);
}
void chooseSettings(State* s){
    if(s->settingsWindow){ShowWindow(s->settingsWindow,SW_SHOW);SetForegroundWindow(s->settingsWindow);return;}
    s->settingsCurrent=static_cast<unsigned>(_wcstoui64(s->data.reply,nullptr,10));s->settingsScope=s->settingsCurrent;
    WNDCLASSW cls{};cls.hInstance=moduleHandle;cls.lpfnWndProc=settingsProcedure;cls.lpszClassName=kSettingsClass;cls.hCursor=LoadCursorW(nullptr,IDC_ARROW);cls.hbrBackground=reinterpret_cast<HBRUSH>(COLOR_WINDOW+1);
    if(!RegisterClassW(&cls)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)return;
    RECT parent{};GetWindowRect(s->parent,&parent);UINT dpi=GetDpiForWindow(s->parent);if(!dpi)dpi=96;
    int width=MulDiv(700,dpi,96),height=MulDiv(758,dpi,96);
    MONITORINFO monitor{sizeof(monitor)};GetMonitorInfoW(MonitorFromWindow(s->parent,MONITOR_DEFAULTTONEAREST),&monitor);
    int x=std::clamp<int>(parent.left+(parent.right-parent.left-width)/2,monitor.rcWork.left,std::max<int>(monitor.rcWork.left,monitor.rcWork.right-width));
    int y=std::clamp<int>(parent.top+(parent.bottom-parent.top-height)/2,monitor.rcWork.top,std::max<int>(monitor.rcWork.top,monitor.rcWork.bottom-height));
    HWND window=CreateWindowExW(WS_EX_DLGMODALFRAME|WS_EX_CONTROLPARENT,kSettingsClass,L"talk helper · 设置",WS_OVERLAPPED|WS_CAPTION|WS_SYSMENU,x,y,width,height,s->parent,nullptr,moduleHandle,s);
    if(window){ShowWindow(window,SW_SHOW);SetForegroundWindow(window);requestSettings(s,s->settingsScope);}
}
bool acceptSettings(State* s,const COPYDATASTRUCT* data){
    if(!s->manager||!data||data->cbData!=sizeof(SettingsPacket)||!data->lpData||data->dwData!=kSettingsData)return false;
    auto p=std::make_unique<SettingsPacket>();memcpy(p.get(),data->lpData,sizeof(*p));
    if(!s->token||p->magic!=kSettingsData||p->version!=kBubbleVersion||p->token!=s->token||p->sequence<=s->settingsSequence||p->scope>1000000||p->context<3||p->context>30||p->thinking>1||p->keyPresent>1||(p->flags!=1&&p->flags!=2)
       ||!terminated(p->assistant,48)||!terminated(p->model,128)||!terminated(p->base,256)||!terminated(p->relationship,128)||!terminated(p->style,1024)||!terminated(p->phrases,1024)||!terminated(p->status,256)||p->key[0]
       ||!terminated(p->selfMbti,16)||!terminated(p->selfRating,4)||!terminated(p->selfStrengths,256)||!terminated(p->selfChallenges,256)
       ||!terminated(p->otherAlias,64)||!terminated(p->otherMbti,16)||!terminated(p->otherRating,4)||!terminated(p->stage,128)
       ||!terminated(p->metContext,256)||!terminated(p->knownDuration,128)||!terminated(p->recentEvents,768)
       ||!terminated(p->contactPattern,512)||!terminated(p->goal,128)||!terminated(p->feeling,256))return false;
    s->settingsSequence=p->sequence;
    if(!s->settingsWindow||p->scope!=s->settingsScope)return true;
    s->settingsWaiting=false;s->settingsLoaded=true;SecureZeroMemory(&s->settingsDraft,sizeof(s->settingsDraft));settingsBusy(s,false);
    if(p->flags==1){
        SetDlgItemTextW(s->settingsWindow,401,p->assistant);SetDlgItemTextW(s->settingsWindow,402,p->model);SetDlgItemTextW(s->settingsWindow,403,p->base);SetDlgItemTextW(s->settingsWindow,404,L"");
        SetDlgItemTextW(s->settingsWindow,406,p->relationship);SetDlgItemTextW(s->settingsWindow,407,p->style);SetDlgItemTextW(s->settingsWindow,408,p->phrases);SetDlgItemInt(s->settingsWindow,409,p->context,FALSE);SendDlgItemMessageW(s->settingsWindow,410,BM_SETCHECK,p->thinking?BST_CHECKED:BST_UNCHECKED,0);
        SetDlgItemTextW(s->settingsWindow,450,p->selfMbti);SetDlgItemTextW(s->settingsWindow,451,p->selfRating);SetDlgItemTextW(s->settingsWindow,452,p->selfStrengths);SetDlgItemTextW(s->settingsWindow,453,p->selfChallenges);
        SetDlgItemTextW(s->settingsWindow,454,p->otherAlias);SetDlgItemTextW(s->settingsWindow,455,p->otherMbti);SetDlgItemTextW(s->settingsWindow,456,p->otherRating);SetDlgItemTextW(s->settingsWindow,457,p->stage);
        SetDlgItemTextW(s->settingsWindow,470,p->metContext);SetDlgItemTextW(s->settingsWindow,471,p->knownDuration);SetDlgItemTextW(s->settingsWindow,472,p->recentEvents);
        SetDlgItemTextW(s->settingsWindow,473,p->contactPattern);SetDlgItemTextW(s->settingsWindow,474,p->goal);SetDlgItemTextW(s->settingsWindow,475,p->feeling);
        SetDlgItemTextW(s->settingsWindow,414,p->keyPresent?L"已配置 Key；留空保留，新 Key 存入 Windows 凭据。":L"尚未配置 Key；请输入 DeepSeek API Key。");
    }
    SetDlgItemTextW(s->settingsWindow,413,*p->status?p->status:L"修改后点击“保存并应用”。Base URL 仅允许 DeepSeek 官方 HTTPS 地址。");return true;
}
