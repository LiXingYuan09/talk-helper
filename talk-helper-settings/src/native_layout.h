#pragma once
#include <map>
#include <memory>
#include <set>
#include <array>
#include <cstring>
#include "follow_geometry.h"
#include "host_compat.h"
namespace nativeflow {
constexpr ULONG_PTR dataId=0x54485212;
#pragma pack(push,1)
struct Header {uint32_t magic,version;uint64_t token,sequence,list;uint32_t count;};
struct Entry {uint64_t item,card;uint32_t padding;};
#pragma pack(pop)
static_assert(sizeof(Header)==36&&sizeof(Entry)==20,"Native layout IPC changed");
class Layout {
    struct Row {uintptr_t object,table;std::array<uintptr_t,145> copy{};short margins[4]{};};
    HWND parent;uintptr_t base=0,list=0,model=0,original=0;
    const hostcompat::Offsets* offsets=nullptr;
    std::array<uintptr_t,13> copy{};std::map<uintptr_t,std::unique_ptr<Row>> rows;
    std::map<uintptr_t,Entry> targets;uint64_t sequence=0;ULONGLONG heartbeat=0;bool changing=false;
    using Height=int(*)(void*,int);using Margins=void(*)(void*,int,int,int,int);using Reload=void(*)(void*,int,int);
    static inline Layout* current=nullptr;
    static bool read(uintptr_t p,void* out,size_t n){SIZE_T done=0;return p&&ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<void*>(p),out,n,&done)&&done==n;}
    static uintptr_t word(uintptr_t p){uintptr_t v=0;read(p,&v,8);return v;}
    static bool qobject(uintptr_t o){auto d=word(o+8);return d&&word(d+8)==o;}
    static std::vector<uintptr_t> children(uintptr_t o){std::vector<uintptr_t> out;auto p=word(word(o+8)+24);int h[4]{};
        if(!read(p,h,16)||h[2]<0||h[3]<h[2]||h[3]>h[1]||h[3]-h[2]>3000)return out;
        for(int i=h[2];i<h[3];++i)out.push_back(word(p+16+8*i));return out;}
    bool belongs(uintptr_t o){for(int depth=0;o&&depth<50;++depth){if(!qobject(o))return false;auto d=word(o+8),data=word(o+40);
        if(data==d+0x120){HWND window=reinterpret_cast<HWND>(word(data));if(window==parent)return true;}
        o=word(d+16);}return false;}
    bool geometry(uintptr_t o,RECT& r){auto d=word(o+8),data=word(o+40);int v[4]{};
        if(!d||data!=d+0x120||!read(data+20,v,sizeof(v))||v[2]<v[0]||v[3]<v[1])return false;
        r={v[0],v[1],v[2]+1,v[3]+1};return true;}
    bool origin(uintptr_t o,POINT& point){point={};for(int depth=0;o&&depth<50;++depth){
        if(!qobject(o))return false;auto d=word(o+8),data=word(o+40);
        if(data==d+0x120){uint32_t attributes=0;if(!read(data+8,&attributes,sizeof(attributes))||!(attributes&(1u<<15))||(attributes&(1u<<16)))return false;
            if(reinterpret_cast<HWND>(word(data))==parent)return true;
            RECT g{};if(!geometry(o,g))return false;point.x+=g.left;point.y+=g.top;}
        o=word(d+16);}return false;}
    bool valid(){return base&&offsets&&list&&word(list)==base+offsets->list&&qobject(list)&&belongs(list)&&word(list+offsets->modelField)==model
        &&word(word(model+0x78))==base+offsets->viewModel&&(word(model)==original||word(model)==reinterpret_cast<uintptr_t>(copy.data()+1));}
    std::set<uintptr_t> items(){std::set<uintptr_t> out;auto vm=word(model+0x78),begin=word(vm+0x88),end=word(vm+0x90);
        if(!begin||end<begin||(end-begin)%16||(end-begin)/16>3000)return out;
        std::vector<uintptr_t> values((end-begin)/8);if(!values.empty()&&!read(begin,values.data(),end-begin))return out;
        for(size_t i=0;i<values.size();i+=2)out.insert(values[i]);return out;}
    int padding(uintptr_t o){auto found=targets.find(word(o+0x250));return found==targets.end()?0:static_cast<int>(found->second.padding);}
    void margins(Row& row){auto d=word(row.object+8);short actual[4]{};if(!read(d+0x108,actual,8))return;
        int bottom=row.margins[3]+padding(row.object);
        if(actual[0]!=row.margins[0]||actual[1]!=row.margins[1]||actual[2]!=row.margins[2]||actual[3]!=bottom)
            reinterpret_cast<Margins>(base+offsets->margins)(reinterpret_cast<void*>(row.object),row.margins[0],row.margins[1],row.margins[2],bottom);}
    static int modelHeight(void* self,int index){auto* s=current;if(!s)return 0;
        int h=reinterpret_cast<Height>(s->base+s->offsets->modelHeight)(self,index);
        if(reinterpret_cast<uintptr_t>(self)!=s->model||h<1||h>100000)return h;
        auto vm=word(s->model+0x78),begin=word(vm+0x88),end=word(vm+0x90);
        if(index>=0&&index<3000&&begin&&end>=begin&&static_cast<uintptr_t>(index)<(end-begin)/16){auto it=s->targets.find(word(begin+index*16));if(it!=s->targets.end())return h+it->second.padding;}
        return h;}
    static int rowHeight(void* self,int width){auto* s=current;if(!s)return -1;auto it=s->rows.find(reinterpret_cast<uintptr_t>(self));if(it==s->rows.end())return -1;
        auto& row=*it->second;s->margins(row);return reinterpret_cast<Height>(word(row.table+0x80))(self,width);}
    static bool rowHasHeight(void* self){auto* s=current;if(!s)return false;auto it=s->rows.find(reinterpret_cast<uintptr_t>(self));if(it==s->rows.end())return false;
        auto& row=*it->second;s->margins(row);return s->padding(row.object)>0||reinterpret_cast<bool(*)(void*)>(word(row.table+0x88))(self);}
    bool discover(){bool added=false;for(auto viewport:children(list))for(auto o:children(viewport)){
        auto vt=word(o);auto old=rows.find(o);if(old!=rows.end()){if(vt==reinterpret_cast<uintptr_t>(old->second->copy.data()+1))continue;rows.erase(old);}
        if(!qobject(o)||word(vt)!=base+offsets->rowMeta||word(o+40)!=word(o+8)+0x120)continue;
        auto row=std::make_unique<Row>();row->object=o;row->table=vt;
        if(!read(vt-8,row->copy.data(),sizeof(row->copy))||!read(word(o+8)+0x108,row->margins,8))continue;
        row->copy[17]=reinterpret_cast<uintptr_t>(&rowHeight);row->copy[18]=reinterpret_cast<uintptr_t>(&rowHasHeight);
        auto ptr=row->copy.data()+1;rows[o]=std::move(row);*reinterpret_cast<uintptr_t*>(o)=reinterpret_cast<uintptr_t>(ptr);added=true;
        if(rows.size()>=512)return added;
    }return added;}
    void reload(){if(changing||!valid())return;changing=true;discover();reinterpret_cast<Reload>(base+offsets->reload)(reinterpret_cast<void*>(list),-1,0);changing=false;}
    bool bind(uintptr_t candidate){base=reinterpret_cast<uintptr_t>(GetModuleHandleW(L"Weixin.dll"));if(!base)return false;
        const auto* build=hostcompat::dllBuild(reinterpret_cast<HMODULE>(base));if(!build)return false;
        offsets=&build->offsets;
        if(word(candidate)!=base+offsets->list||!qobject(candidate)||!belongs(candidate))return false;
        auto newModel=word(candidate+offsets->modelField),vt=word(newModel);
        if(vt!=base+offsets->model||word(vt+0x50)!=base+offsets->modelHeight||word(word(newModel+0x78))!=base+offsets->viewModel)return false;
        if(!read(vt-8,copy.data(),sizeof(copy)))return false;
        list=candidate;model=newModel;original=vt;copy[11]=reinterpret_cast<uintptr_t>(&modelHeight);current=this;
        *reinterpret_cast<uintptr_t*>(model)=reinterpret_cast<uintptr_t>(copy.data()+1);return true;}
public:
    explicit Layout(HWND parent):parent(parent){}
    ~Layout(){clear();if(current==this)current=nullptr;}
    void clear(){bool wasValid=valid();targets.clear();
        for(auto& [o,row]:rows)if(qobject(o)&&word(o)==reinterpret_cast<uintptr_t>(row->copy.data()+1)){
            *reinterpret_cast<uintptr_t*>(o)=row->table;
            reinterpret_cast<Margins>(base+offsets->margins)(reinterpret_cast<void*>(o),row->margins[0],row->margins[1],row->margins[2],row->margins[3]);}
        if(model&&word(model)==reinterpret_cast<uintptr_t>(copy.data()+1))*reinterpret_cast<uintptr_t*>(model)=original;
        if(wasValid)reinterpret_cast<Reload>(base+offsets->reload)(reinterpret_cast<void*>(list),-1,0);
        rows.clear();list=model=original=0;offsets=nullptr;heartbeat=0;if(current==this)current=nullptr;}
    bool accept(const COPYDATASTRUCT* packet,uint64_t token){if(!packet||packet->dwData!=dataId||packet->cbData<sizeof(Header)||!packet->lpData||!token)return false;
        Header h{};memcpy(&h,packet->lpData,sizeof(h));if(h.magic!=dataId||h.version!=13||h.token!=token||h.sequence<=sequence||h.count>3000||packet->cbData!=sizeof(Header)+h.count*sizeof(Entry))return false;
        if(h.count==0){sequence=h.sequence;clear();return true;}
        uintptr_t host=reinterpret_cast<uintptr_t>(GetModuleHandleW(L"Weixin.dll"));
        const auto* build=hostcompat::dllBuild(reinterpret_cast<HMODULE>(host));if(!build)return false;
        const auto& spec=build->offsets;
        if(!host||word(h.list)!=host+spec.list||!qobject(h.list))return false;
        auto candidateModel=word(h.list+spec.modelField),vm=word(candidateModel+0x78),begin=word(vm+0x88),end=word(vm+0x90);
        if(word(vm)!=host+spec.viewModel||!begin||end<begin||(end-begin)%16||(end-begin)/16>3000)return false;
        std::set<uintptr_t> allowed;for(auto p=begin;p<end;p+=16)allowed.insert(word(p));
        std::map<uintptr_t,Entry> next;std::set<uint64_t> cardIds;
        for(uint32_t i=0;i<h.count;++i){Entry e{};memcpy(&e,reinterpret_cast<const char*>(packet->lpData)+sizeof(Header)+i*sizeof(Entry),sizeof(e));
            if(!e.item||!e.card||e.card>100000000||e.padding<110||e.padding>512||!allowed.count(e.item)||word(e.item)!=host+spec.item||next.count(e.item)||!cardIds.insert(e.card).second)return false;
            next[e.item]=e;}
        if(h.list!=list||!valid()){clear();if(!bind(h.list))return false;}
        bool changed=next.size()!=targets.size();if(!changed)for(auto& [p,e]:next){auto old=targets.find(p);if(old==targets.end()||memcmp(&e,&old->second,sizeof(e))){changed=true;break;}}
        targets=std::move(next);sequence=h.sequence;heartbeat=GetTickCount64();if(changed)reload();return true;}
    void tick(){if(!list)return;if(!valid()){clear();return;}
        bool changed=false;auto allowed=items();for(auto it=targets.begin();it!=targets.end();)if(!allowed.count(it->first)){it=targets.erase(it);changed=true;}else ++it;
        if(discover()||changed)reload();}
    bool contains(uint64_t card)const {for(const auto& entry:targets)if(entry.second.card==card)return true;return false;}
    uintptr_t listAddress()const{return list;}
    // Pooled Qt widgets can change message ownership. Resolve their current item
    // every time, and hide instead of attaching an old result to a recycled row.
    std::map<uint64_t,nativefollow::Position> positions(UINT dpi){std::map<uint64_t,nativefollow::Position> out;
        if(!valid())return out;RECT bounds{};POINT offset{};
        if(!geometry(list,bounds)||!origin(list,offset))return out;
        const double scale=(dpi?dpi:96)/96.;auto px=[&](LONG n){return static_cast<LONG>(std::lround(n*scale));};
        RECT area{px(offset.x),px(offset.y),px(offset.x+bounds.right-bounds.left),px(offset.y+bounds.bottom-bounds.top)};
        std::set<uint64_t> duplicates;const auto allowed=items();
        for(const auto& entry:rows){auto o=entry.first;const auto& row=*entry.second;
            if(word(o)!=reinterpret_cast<uintptr_t>(row.copy.data()+1)||!qobject(o))continue;
            auto item=word(o+0x250);auto found=targets.find(item);if(found==targets.end()||!allowed.count(item))continue;
            RECT g{};POINT at{};short actual[4]{};
            if(!geometry(o,g)||!origin(o,at)||!read(word(o+8)+0x108,actual,8)||actual[3]!=row.margins[3]+found->second.padding)continue;
            RECT physical{px(at.x),px(at.y),px(at.x+g.right-g.left),px(at.y+g.bottom-g.top)};
            const auto card=found->second.card;
            auto value=nativefollow::project(area,physical,found->second.padding,dpi);
            if(!out.emplace(card,value).second)duplicates.insert(card);
        }
        for(auto card:duplicates)out.erase(card);return out;
    }
};
}
