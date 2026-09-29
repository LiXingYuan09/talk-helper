#pragma once
#include "probe.h"
#include <gdiplus.h>
#include <algorithm>
#include <string>
#include <vector>
#include <memory>
namespace inlineview {
using namespace Gdiplus;
struct Item {RectF detail,copy,next;};
struct Layout {std::vector<Item> items;float height=0;};
inline Color rgb(int r,int g,int b){return Color(255,r,g,b);}
inline void rounded(Graphics& g,const RectF& r,float radius,Color color){
    float d=std::min(radius*2,std::min(r.Width,r.Height));GraphicsPath path;
    path.AddArc(r.X,r.Y,d,d,180,90);path.AddArc(r.GetRight()-d,r.Y,d,d,270,90);
    path.AddArc(r.GetRight()-d,r.GetBottom()-d,d,d,0,90);path.AddArc(r.X,r.GetBottom()-d,d,d,90,90);
    path.CloseFigure();SolidBrush brush(color);g.FillPath(&brush,&path);
}
inline float measure(Graphics& g,const wchar_t* value,float width){
    Font font(L"Microsoft YaHei UI",16,FontStyleRegular,UnitPixel);RectF bound;
    g.MeasureString(value,-1,&font,RectF(0,0,std::max(40.f,width),10000),nullptr,&bound);return bound.Height;
}
inline void text(Graphics& g,const wchar_t* value,float size,Color color,RectF rect,bool center=false){
    Font font(L"Microsoft YaHei UI",size,FontStyleRegular,UnitPixel);StringFormat f;
    f.SetTrimming(StringTrimmingEllipsisCharacter);
    if(center){f.SetAlignment(StringAlignmentCenter);f.SetLineAlignment(StringAlignmentCenter);}
    SolidBrush brush(color);g.DrawString(value,-1,&font,rect,&f,&brush);
}
inline Layout layout(Graphics& g,const BubblePacket& p,float width,float height,bool expanded){
    Layout result;result.height=expanded?measure(g,p.body,width-28)+112:height;
    result.items.push_back({RectF(width-58,12,44,28),expanded?RectF(14,height-40,104,28):RectF(),expanded?RectF(126,height-40,92,28):RectF()});return result;
}
inline void paint(Graphics& g,const BubblePacket& p,float width,float height,bool expanded,float scroll){
    g.SetSmoothingMode(SmoothingModeAntiAlias);g.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);
    const bool analysis=!expanded&&!(p.flags&kFlagCompact)&&height>=220;
    const auto background=(p.flags&kFlagControl)?rgb(245,250,246):rgb(237,237,237);
    g.Clear(background);rounded(g,RectF(0,0,width,height),8,background);
    if(!expanded&&(p.flags&kFlagCompact)){
        text(g,(p.flags&kFlagControl)?p.status:(p.flags&kFlagPaused)?L"talk helper · 已暂停":L"talk helper · 查看建议",14,rgb(0,137,80),RectF(8,0,width-16,height),true);return;
    }
    std::wstring label=*p.assistantName?p.assistantName:L"talk helper";
    if(p.tension>=0&&!analysis)label+=L" · 紧张度 "+std::to_wstring(p.tension)+L"/9";
    text(g,label.c_str(),analysis?14:16,analysis?rgb(49,49,49):rgb(0,137,80),RectF(14,13,width-82,28));
    auto positions=layout(g,p,width,height,expanded);const auto& i=positions.items[0];
    rounded(g,i.detail,8,analysis?rgb(222,222,222):rgb(227,240,231));text(g,expanded?L"收起":L"详情",12,analysis?rgb(62,62,62):rgb(47,95,78),i.detail,true);
    if(expanded){
        auto saved=g.Save();g.SetClip(RectF(14,56,width-28,height-108));
        text(g,p.body,16,rgb(28,61,48),RectF(14,56-scroll,width-28,std::max(100.f,positions.height)),false);g.Restore(saved);
        rounded(g,i.copy,7,rgb(227,240,231));rounded(g,i.next,7,rgb(227,240,231));
        text(g,L"复制回复",13,rgb(47,95,78),i.copy,true);text(g,L"换一条",13,rgb(47,95,78),i.next,true);
    }else if(analysis)text(g,p.status,14,rgb(31,31,31),RectF(14,49,width-28,height-56));
    else text(g,p.status,16,rgb(28,61,48),RectF(14,56,width-28,40));
}
inline bool contains(const RectF& r,float x,float y){return r.Width>0&&x>=r.X&&y>=r.Y&&x<r.GetRight()&&y<r.GetBottom();}
inline bool saveReference(const wchar_t* path){
    BubblePacket p{};p.tension=4;lstrcpyW(p.assistantName,L"talk helper · 19:12 · 模型参考");
    lstrcpyW(p.status,L"信息足够直接答复？\r\n- 是 18%   - 先核实 82%\r\n可能的对话用途 · 模型权重\r\n- 核对过往内容 72%\r\n- 闲聊或分享 20%\r\n- 其他 8%\r\n紧张度：4/9\r\n当前动作\r\n- 先翻聊天记录，确认对方指的是哪件事");
    Bitmap bmp(304,252,PixelFormat32bppARGB);Graphics g(&bmp);paint(g,p,304,252,false,0);
    UINT count=0,size=0;GetImageEncodersSize(&count,&size);std::vector<BYTE> bytes(size);
    auto* codecs=reinterpret_cast<ImageCodecInfo*>(bytes.data());GetImageEncoders(count,size,codecs);
    for(UINT i=0;i<count;i++)if(!wcscmp(codecs[i].MimeType,L"image/png"))return bmp.Save(path,&codecs[i].Clsid,nullptr)==Ok;
    return false;
}
}
