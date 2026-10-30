#include "../runtime/rdr2_100_pack_trace.h"
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <thread>
#include <stdexcept>
#include <vector>

namespace {
static constexpr std::uint64_t kBase=UINT64_C(0x10000000000);
static constexpr std::uint64_t kMethodRvas[112] = {
0x452a380,0x452a3f0,0x452a480,0x452a620,0x4521050,0x45210a0,
0x452a780,0x452a800,0x45210d0,0x452a860,0x45210e0,0x452a870,
0x45210f0,0x452b9d0,0x452ba60,0x4521190,0x452ba80,0x452ba90,
0x452baa0,0x452be00,0x452be10,0x452be20,0x452be30,0x452be80,
0x4521280,0x4521290,0x45212a0,0x45212b0,0x45212c0,0x45212d0,
0x45212e0,0x45212f0,0x452bed0,0x4521360,0x452bf80,0x4521640,
0x452bfe0,0x452bff0,0x4521940,0x452cc80,0x452d190,0x4521970,
0x4521980,0x45219c0,0x452d1a0,0x45219e0,0x452d220,0x452d250,
0x4521a00,0x4521a70,0x452d260,0x4521bd0,0x4521eb0,0x4521ec0,
0x452d340,0x452d400,0x452d450,0x452d460,0x4521f10,0x4521f20,
0x4521f30,0x452d470,0x452d480,0x452d490,0x452d510,0x452d530,
0x452d550,0x452d560,0x452dea0,0x452dee0,0x452df00,0x452df10,
0x452df20,0x452e0c0,0x452e7a0,0x452e7f0,0x452e810,0x452e820,
0x452e850,0x452e870,0x452e880,0x452e8d0,0x452e8f0,0x452e910,
0x452e960,0x452e970,0x452eb90,0x452ec50,0x452ec60,0x452ecc0,
0x4521f90,0x4521fa0,0x452ecd0,0x452ecf0,0x452ed00,0x452ed10,
0x452ed20,0x452ed30,0x452ed40,0x4521fb0,0x452ed50,0x452ed80,
0x452eda0,0x452ee00,0x452ee30,0x452ee50,0x452ee80,0x452eea0,
0x452eec0,0x452eee0,0x452ef00,0x452ef20
};
static constexpr unsigned char kPrefixes[4][16] = {
 {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x48,0x83,0xec},
 {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x54,0x53,0x49,0x89,0xd6,0x31,0xd2},
 {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x50,0x48,0x89},
 {0x48,0x8b,0x47,0x10,0x48,0x8b,0x77,0x20,0x48,0x8b,0x38,0x4c,0x8b,0x4f,0x70,0x48}
};
static constexpr std::uint64_t kPrefixRvas[] = {
 0x452A480,0x452A780,0x452B9D0,0x452BA60
};
struct ReadContext {
    std::atomic<int> calls{0};
    bool tamper_table=false;
    bool deny_rva=false;
    bool tamper_boundary=false;
};
static void write_le64(void* out, std::uint64_t value) {
    auto* b=static_cast<unsigned char*>(out);
    for(unsigned i=0;i<8u;i++)b[i]=(unsigned char)(value>>(i*8u));
}
static int fake_rva(void* context, std::uint64_t rva,
                     void* out, std::size_t size) {
    auto* c=static_cast<ReadContext*>(context);
    if(c)c->calls.fetch_add(1,std::memory_order_relaxed);
    if(!c || c->deny_rva)return -1;
    constexpr char type[]="N4rage11fiPackfile8E";
    if(rva==0x05D7DE40 && size==sizeof(type)){
        std::memcpy(out,type,size); return 0;
    }
    if((rva==0x066B00E8 || rva==RDR2_100_PACK_VTABLE_RVA+112u*8u) && size==8){
        write_le64(out,c->tamper_boundary ? 1u : 0u);
        return 0;
    }
    if(rva==0x066B00F0 && size==8){
        write_le64(out,kBase+0x066B0480);return 0;
    }
    if(rva>=RDR2_100_PACK_VTABLE_RVA &&
       (rva-RDR2_100_PACK_VTABLE_RVA)%8==0 && size==8) {
        const auto index=(rva-RDR2_100_PACK_VTABLE_RVA)/8;
        if(index<112) {
            write_le64(out,kBase+kMethodRvas[index]);return 0;
        }
    }
    if(rva==RDR2_100_PACK_VTABLE_RVA && size==112*8u) {
        auto* bytes=static_cast<unsigned char*>(out);
        for(unsigned i=0;i<112u;i++) {
            std::uint64_t item=kBase+kMethodRvas[i];
            if(c->tamper_table && i==100)item+=16;
            write_le64(bytes+i*8u,item);
        }
        return 0;
    }
    for(unsigned i=0;i<4u;i++)
        if(rva==kPrefixRvas[i] && size==16) {
            std::memcpy(out,kPrefixes[i],16);return 0;
        }
    return -1;
}
struct RegistryObject { void* vptr; std::uint16_t slot; std::uint8_t reserved[6]; };
struct RegistryContext {
    std::atomic<int> calls{0};
    RegistryObject* good=nullptr;
    RegistryObject* invalid=nullptr;
    bool fail_registry=false;
};
static int fake_absolute_registry(void* p,std::uint64_t address,
                                  void* out,std::size_t bytes) {
    auto* c=static_cast<RegistryContext*>(p);
    c->calls.fetch_add(1,std::memory_order_relaxed);
    const std::uint64_t region=kBase+RDR2_100_REGISTRY_RVA;
    if(c->fail_registry && address==region+3*8)return -1;
    if(address>=region && address<region+65536*8 &&
       (address-region)%8==0 && bytes==8) {
        unsigned slot=(unsigned)((address-region)/8);
        auto* obj=slot==3?c->good:slot==9?c->invalid:nullptr;
        write_le64(out,reinterpret_cast<std::uintptr_t>(obj));return 0;
    }
    if(address==reinterpret_cast<std::uintptr_t>(c->good) &&
       bytes==8) {
        std::memcpy(out,&c->good->vptr,bytes);return 0;
    }
    if(address==reinterpret_cast<std::uintptr_t>(c->good)+8u &&
       bytes==2) {
        std::memcpy(out,&c->good->slot,bytes);return 0;
    }
    if(address==reinterpret_cast<std::uintptr_t>(c->invalid) && bytes==8) {
        std::memcpy(out,&c->invalid->vptr,bytes);return 0;
    }
    if(address==reinterpret_cast<std::uintptr_t>(c->invalid)+8u && bytes==2) {
        std::memcpy(out,&c->invalid->slot,bytes);return 0;
    }
    return -1;
}
struct FakeDevice { void** vptr; };
static std::atomic<unsigned> opened{0};
static std::atomic<unsigned> callbacks{0};
static std::atomic<bool> gate{false}, entered{false}, release{false};
static std::atomic<bool> original_throws{false}, callback_throws{false};
static std::uint64_t original_open(void* self,const char* path,std::uint8_t flag) {
    assert(self!=nullptr && path!=nullptr && flag==1);
    opened.fetch_add(1u,std::memory_order_relaxed);
    if(original_throws.load(std::memory_order_acquire))
        throw std::runtime_error("synthetic original failure");
    if(gate.load(std::memory_order_acquire)) {
        entered.store(true,std::memory_order_release);
        while(!release.load(std::memory_order_acquire))std::this_thread::yield();
    }
    return UINT64_C(0x1122334455667788);
}
static void on_open(void*,const char* path,std::uint8_t flag) {
    assert(path && flag==1);
    callbacks.fetch_add(1u,std::memory_order_relaxed);
    if(callback_throws.load(std::memory_order_acquire))
        throw std::runtime_error("synthetic callback failure");
}
static void dummy_slot(void) {}
#define CHECK(x) do{ if(!(x)){std::fprintf(stderr, "TEST FAILED line %d: %s\n",__LINE__,#x);return 2;}}while(0)
} // namespace

int main() {
    ReadContext ctx{};
    Rdr2_100PackPreflight info{};
    CHECK(rdr2_100_pack_preflight(fake_rva,&ctx,1,0,kBase,&info)==RDR2_100_TRACE_OK);
    CHECK(info.expected_vptr==kBase+RDR2_100_PACK_VTABLE_RVA);
    CHECK(info.expected_open==kBase+RDR2_100_PACK_OPEN_RVA);
    CHECK(info.vtable_methods==112);
    CHECK(info.vtable_fingerprint==RDR2_100_PACK_VTABLE_FNV64);
    ctx.calls.store(0);
    CHECK(rdr2_100_pack_preflight(fake_rva,&ctx,1,32,kBase,&info)==
          RDR2_100_TRACE_UNSUPPORTED_PATCH);
    CHECK(ctx.calls.load()==0 && info.expected_vptr==0);
    CHECK(rdr2_100_pack_preflight(fake_rva,&ctx,2,0,kBase,&info)==
          RDR2_100_TRACE_UNSUPPORTED_PATCH);
    CHECK(ctx.calls.load()==0);
    ctx.tamper_table=true;
    CHECK(rdr2_100_pack_preflight(fake_rva,&ctx,1,0,kBase,&info)==
          RDR2_100_TRACE_PROFILE_MISMATCH);
    CHECK(info.expected_open==0);
    ctx.tamper_table=false;
    ctx.tamper_boundary=true;
    CHECK(rdr2_100_pack_preflight(fake_rva,&ctx,1,0,kBase,&info)==
          RDR2_100_TRACE_PROFILE_MISMATCH);
    ctx.tamper_boundary=false;
    ctx.deny_rva=true;
    CHECK(rdr2_100_pack_preflight(fake_rva,&ctx,1,0,kBase,&info)!=RDR2_100_TRACE_OK);
    ctx.deny_rva=false;
    CHECK(rdr2_100_pack_preflight(fake_rva,&ctx,1,0,UINT64_MAX,&info)!=RDR2_100_TRACE_OK);

    RegistryObject good{reinterpret_cast<void*>(kBase+RDR2_100_PACK_VPTR_RVA),3,{0}};
    RegistryObject bad{reinterpret_cast<void*>(UINT64_C(0x12345678)),9,{0}};
    RegistryContext reg{};
    reg.good=&good;reg.invalid=&bad;
    std::uint64_t result[4]={};
    std::size_t count=99;
    CHECK(rdr2_100_find_pack_instances(fake_absolute_registry,&reg,1,32,kBase,
          0,16,result,4,&count)==RDR2_100_REGISTRY_UNSUPPORTED_VERSION);
    CHECK(reg.calls.load()==0 && count==0);
    CHECK(rdr2_100_find_pack_instances(fake_absolute_registry,&reg,1,0,kBase,
          0,16,result,4,&count)==RDR2_100_REGISTRY_OK);
    CHECK(count==1 && result[0]==reinterpret_cast<std::uintptr_t>(&good));
    CHECK(rdr2_100_find_pack_instances(fake_absolute_registry,&reg,1,0,kBase,
          0,16,nullptr,0,&count)==RDR2_100_REGISTRY_TRUNCATED && count==1);
    reg.fail_registry=true;
    CHECK(rdr2_100_find_pack_instances(fake_absolute_registry,&reg,1,0,kBase,
          0,16,result,4,&count)==RDR2_100_REGISTRY_UNMAPPED);
    reg.fail_registry=false;
    CHECK(rdr2_100_find_pack_instances(fake_absolute_registry,&reg,1,0,kBase,
          0,5000,result,4,&count)==RDR2_100_REGISTRY_BAD_ARGUMENT);

    CHECK(rdr2_100_pack_trace_may_unload()==1);
    void* original_table[RDR2_100_PACK_VTABLE_SLOTS+2]={};
    original_table[0]=reinterpret_cast<void*>(UINT64_C(0));
    original_table[1]=reinterpret_cast<void*>(UINT64_C(0xfeedbeef));
    for(unsigned i=0;i<RDR2_100_PACK_VTABLE_SLOTS;i++)
        original_table[i+2]=reinterpret_cast<void*>(dummy_slot);
    original_table[2+RDR2_100_PACK_OPEN_SLOT]=
        reinterpret_cast<void*>(original_open);
    FakeDevice device{original_table+2};
    CHECK(rdr2_100_pack_trace_host_fixture_attach(&device,original_table+3,
        original_open,on_open,nullptr)==RDR2_100_TRACE_STALE_INSTANCE);
    CHECK(rdr2_100_pack_trace_host_fixture_attach(&device,original_table+2,
        original_open,on_open,nullptr)==RDR2_100_TRACE_OK);
    CHECK(rdr2_100_pack_trace_is_attached(&device));
    CHECK(rdr2_100_pack_trace_may_unload()==0);
    CHECK(device.vptr!=original_table+2);
    CHECK(device.vptr[-2]==original_table[0] && device.vptr[-1]==original_table[1]);
    CHECK(device.vptr[13]==original_table[15]);
    CHECK(device.vptr[111]==original_table[113]);

    const auto thunk=reinterpret_cast<Rdr2_100PackOpenFn>(device.vptr[2]);
    CHECK(thunk(&device,"common:/data/hello.meta",1)==UINT64_C(0x1122334455667788));
    CHECK(opened.load()==1u && callbacks.load()==1u);
    CHECK(rdr2_100_pack_trace_open_calls()==1u);
    CHECK(rdr2_100_pack_trace_active_calls()==0u);
    gate.store(true);
    std::thread slow([&]{
        assert(thunk(&device,"common:/data/slow.meta",1)==UINT64_C(0x1122334455667788));
    });
    while(!entered.load())std::this_thread::yield();
    CHECK(rdr2_100_pack_trace_detach(&device)==RDR2_100_TRACE_BUSY);
    CHECK(rdr2_100_pack_trace_is_attached(&device));
    release.store(true);
    slow.join();
    gate.store(false);

    constexpr int kWorkers=4, kOps=125;
    std::vector<std::thread> threads;
    for(int i=0;i<kWorkers;i++)
        threads.emplace_back([&] {
            for(int j=0;j<kOps;j++)
                assert(thunk(&device,"common:/data/thread.meta",1)==
                      UINT64_C(0x1122334455667788));
        });
    for(auto& thread:threads)thread.join();
    CHECK(opened.load()==1u+1u+kWorkers*kOps);
    original_throws.store(true);
    bool original_exception_seen=false;
    try { (void)thunk(&device,"common:/data/exception.meta",1); }
    catch(const std::runtime_error&) { original_exception_seen=true; }
    CHECK(original_exception_seen && rdr2_100_pack_trace_active_calls()==0u);
    original_throws.store(false);
    callback_throws.store(true);
    CHECK(thunk(&device,"common:/data/callback-exception.meta",1)==
          UINT64_C(0x1122334455667788));
    CHECK(rdr2_100_pack_trace_active_calls()==0u);
    callback_throws.store(false);
    CHECK(thunk(&device,"common:/data/post-exception.meta",1)==
          UINT64_C(0x1122334455667788));
    CHECK(rdr2_100_pack_trace_detach(&device)==RDR2_100_TRACE_OK);
    CHECK(!rdr2_100_pack_trace_is_attached(&device));
    CHECK(device.vptr==original_table+2);
    const unsigned callback_count=callbacks.load();
    /* A game caller could have retained a thunk pointer before detach.
     * It must still call original safely, but never trace after retire. */
    CHECK(thunk(&device,"common:/data/stale-pointer.meta",1)==
          UINT64_C(0x1122334455667788));
    CHECK(callbacks.load()==callback_count);
    CHECK(rdr2_100_pack_trace_may_unload()==0);
    CHECK(rdr2_100_pack_trace_detach(&device)==RDR2_100_TRACE_NOT_ATTACHED);
    CHECK(rdr2_100_pack_trace_host_fixture_attach(&device,original_table+2,
        original_open,on_open,nullptr)==RDR2_100_TRACE_ALREADY_USED);
    std::puts("RDR2_100_HARDENED_VTABLE_TRACE_AND_REGISTRY_PASSED");
    return 0;
}
