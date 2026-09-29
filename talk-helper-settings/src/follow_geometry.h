#pragma once
#include <windows.h>
#include <algorithm>
#include <cmath>
namespace nativefollow {
struct Position {RECT bounds{},clip{};bool visible=false;};
// Geometry comes from the already verified Qt row, never from a stale UIA scan.
inline Position project(const RECT& area,const RECT& row,int padding,UINT dpi) {
    Position p;const double scale=(dpi?dpi:96)/96.;
    auto px=[&](int n){return static_cast<LONG>(std::lround(n*scale));};
    if(padding<110||padding>512||area.right-area.left<px(320)||row.bottom-row.top<px(padding))return p;
    const int cardHeight=padding>=294?252:101;
    p.bounds={area.left+px(68),row.bottom-px(padding)+px(6),area.left+px(372),row.bottom-px(padding)+px(6+cardHeight)};
    RECT inset={area.left+px(8),area.top,area.right-px(8),area.bottom};
    if(p.bounds.left<inset.left||p.bounds.right>inset.right||p.bounds.top<row.top||p.bounds.bottom>row.bottom)return p;
    p.visible=IntersectRect(&p.clip,&p.bounds,&inset)!=0;return p;
}
}
