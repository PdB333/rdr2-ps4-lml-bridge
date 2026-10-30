#include "rdr2_100_pack_trace.h"
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace {
enum Phase : int { Fresh=0, Preparing=1, Attached=2, Detaching=3,
                   Retired=4, Unsafe=5 };
static constexpr std::uint64_t kRTTI = UINT64_C(0x066B0480);
static constexpr std::size_t kBytes = RDR2_100_PACK_VTABLE_SLOTS * 8u;

struct Hook {
    /* Itanium ABI header is at [-2],[-1] relative to address_point. */
    alignas(16) void* entries[RDR2_100_PACK_VTABLE_SLOTS + 2u] = {};
    void* device = nullptr;
    void* original_address_point = nullptr;
    Rdr2_100PackOpenFn original_open = nullptr;
    Rdr2_100PackTraceFn callback = nullptr;
    void* callback_context = nullptr;
};
static Hook g_hook;
static std::atomic<int> g_phase{Fresh};
static std::atomic<std::uint32_t> g_active{0u};
static std::atomic<std::uint64_t> g_open_count{0u};
static std::atomic_flag g_callback_busy = ATOMIC_FLAG_INIT;

/* Game code may throw a C++ exception through virtual Open. RAII keeps
 * the quiescence counter accurate even if ORIGINAL Open unwinds.
 * A user trace callback is kept outside the game's exception contract:
 * exceptions from the callback are suppressed, its gate always released.
 * The callback must still be bounded, non-blocking and allocation-free.
 */
struct ActiveScope {
    ActiveScope() { g_active.fetch_add(1u, std::memory_order_acq_rel); }
    ~ActiveScope() { g_active.fetch_sub(1u, std::memory_order_acq_rel); }
};
struct CallbackScope {
    ~CallbackScope() { g_callback_busy.clear(std::memory_order_release); }
};
static std::uint64_t trace_open(void* self, const char* path, std::uint8_t flag) {
    ActiveScope active;
    g_open_count.fetch_add(1u, std::memory_order_relaxed);
    const auto original = g_hook.original_open;
    const std::uint64_t answer =
        original ? original(self, path, flag) : UINT64_MAX;
    if (self == g_hook.device &&
        g_phase.load(std::memory_order_acquire) == Attached &&
        g_hook.callback &&
        !g_callback_busy.test_and_set(std::memory_order_acquire)) {
        CallbackScope gate;
        try {
            g_hook.callback(g_hook.callback_context, path, flag);
        } catch (...) {
            /* Never let a logging callback unwind into the RAGE engine. */
        }
    }
    return answer;
}

static std::uint64_t le64(const unsigned char* p) {
    std::uint64_t v=0;
    for(unsigned i=0;i<8u;i++)v|=(std::uint64_t)p[i]<<(8u*i);
    return v;
}
static std::uint64_t fnv_append(std::uint64_t value, std::uint64_t n) {
    for(unsigned i=0;i<8u;i++) {
        value ^= (std::uint8_t)(n>>(8u*i));
        value *= UINT64_C(0x100000001B3);
    }
    return value;
}
static int verify_full_table(const unsigned char raw[kBytes],
                             std::uint64_t base) {
    std::uint64_t h=UINT64_C(0xCBF29CE484222325);
    for(std::size_t i=0;i<RDR2_100_PACK_VTABLE_SLOTS;i++) {
        const std::uint64_t address=le64(raw+i*8u);
        if (address < base || address-base < UINT64_C(0x04521050)
            || address-base > UINT64_C(0x0452EF20))
            return RDR2_100_TRACE_PROFILE_MISMATCH;
        h=fnv_append(h,address-base);
    }
    return h == RDR2_100_PACK_VTABLE_FNV64 ?
        RDR2_100_TRACE_OK : RDR2_100_TRACE_PROFILE_MISMATCH;
}
static int reserve_and_install(void* device, void* expected_vptr,
      const unsigned char table[kBytes], std::uint64_t expected_open,
      std::uint64_t expected_rtti, void* offset_to_top,
      Rdr2_100PackTraceFn callback, void* ctx) {
    int fresh=Fresh;
    if (!g_phase.compare_exchange_strong(fresh, Preparing,
            std::memory_order_acq_rel, std::memory_order_acquire))
        return (fresh == Retired || fresh == Unsafe) ?
            RDR2_100_TRACE_ALREADY_USED : RDR2_100_TRACE_BUSY;

    /* A failed attach has never published the shadow table. Thus retrying
     * is safe. Once an attach succeeds the memory is NEVER reused, even
     * after detach (game threads may cache virtual function pointers).
     */
    g_hook.entries[0] = offset_to_top;
    g_hook.entries[1] = reinterpret_cast<void*>(
        static_cast<std::uintptr_t>(expected_rtti));
    for(std::size_t i=0;i<RDR2_100_PACK_VTABLE_SLOTS;i++)
        g_hook.entries[i+2u] = reinterpret_cast<void*>(
            static_cast<std::uintptr_t>(le64(table+i*8u)));
    g_hook.original_open = reinterpret_cast<Rdr2_100PackOpenFn>(
        static_cast<std::uintptr_t>(expected_open));
    g_hook.entries[RDR2_100_PACK_OPEN_SLOT+2u] =
        reinterpret_cast<void*>(trace_open);
    g_hook.device=device;
    g_hook.original_address_point=expected_vptr;
    g_hook.callback=callback;
    g_hook.callback_context=ctx;

    void* seen=expected_vptr;
    void* const shadow = &g_hook.entries[2u];
    const bool installed=__atomic_compare_exchange_n(
        static_cast<void**>(device), &seen, shadow, false,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    if(!installed) {
        g_phase.store(Fresh, std::memory_order_release);
        return RDR2_100_TRACE_STALE_INSTANCE;
    }
    g_phase.store(Attached, std::memory_order_release);
    return RDR2_100_TRACE_OK;
}
} // namespace

extern "C" int rdr2_100_pack_preflight(
    Rdr2_100ReadAbsolute read_rva, void* ctx,
    std::uint32_t major, std::uint32_t minor, std::uint64_t base,
    Rdr2_100PackPreflight* out) {
    if(out)std::memset(out,0,sizeof(*out));
    if(major!=1u || minor!=0u)return RDR2_100_TRACE_UNSUPPORTED_PATCH;
    if(!read_rva || !out || base>UINT64_MAX-RDR2_100_PACK_VTABLE_RVA ||
       base>UINT64_MAX-RDR2_100_PACK_OPEN_RVA)
        return RDR2_100_TRACE_BAD_ARGUMENT;
    LmlEbootVfsProfile p = {};
    if (lml_eboot_verify_profile(read_rva, ctx, base,
                                  major, minor, &p) != 0)
        return RDR2_100_TRACE_PROFILE_MISMATCH;
    if(p.packfile8_vtable_rva!=RDR2_100_PACK_VTABLE_RVA ||
       p.open_rva!=RDR2_100_PACK_OPEN_RVA)
        return RDR2_100_TRACE_PROFILE_MISMATCH;
    unsigned char metadata[8]={};
    /* Itanium's offset-to-top is exactly zero for this complete object.
     * The zero entry after slot 111 is the next vtable's RTTI preamble.
     */
    if(read_rva(ctx,RDR2_100_PACK_VTABLE_RVA-16u,metadata,8u)!=0)
        return RDR2_100_TRACE_UNMAPPED;
    if(le64(metadata)!=0u)return RDR2_100_TRACE_PROFILE_MISMATCH;
    if(read_rva(ctx,RDR2_100_PACK_VTABLE_RVA+
               RDR2_100_PACK_VTABLE_SLOTS*8u,metadata,8u)!=0)
        return RDR2_100_TRACE_UNMAPPED;
    if(le64(metadata)!=0u)return RDR2_100_TRACE_PROFILE_MISMATCH;
    unsigned char methods[kBytes] = {};
    if(read_rva(ctx,RDR2_100_PACK_VTABLE_RVA,methods,sizeof(methods))!=0)
        return RDR2_100_TRACE_UNMAPPED;
    if(verify_full_table(methods,base)!=RDR2_100_TRACE_OK)
        return RDR2_100_TRACE_PROFILE_MISMATCH;
    out->expected_vptr=base+RDR2_100_PACK_VTABLE_RVA;
    out->expected_open=base+RDR2_100_PACK_OPEN_RVA;
    out->vtable_fingerprint=RDR2_100_PACK_VTABLE_FNV64;
    out->vtable_methods=RDR2_100_PACK_VTABLE_SLOTS;
    return RDR2_100_TRACE_OK;
}

extern "C" int rdr2_100_pack_trace_attach_checked(
    void* device, std::uint32_t major, std::uint32_t minor,
    std::uint64_t base, Rdr2_100ReadAbsolute read_rva,
    Rdr2_100ReadAbsolute read_absolute, void* ctx,
    Rdr2_100PackTraceFn callback, void* trace_context) {
    if(major!=1u || minor!=0u)return RDR2_100_TRACE_UNSUPPORTED_PATCH;
    if(!device || !read_rva || !read_absolute ||
       (reinterpret_cast<std::uintptr_t>(device)&7u))
        return RDR2_100_TRACE_BAD_ARGUMENT;
    const int phase=g_phase.load(std::memory_order_acquire);
    if(phase!=Fresh)
        return phase==Retired || phase==Unsafe ?
            RDR2_100_TRACE_ALREADY_USED : RDR2_100_TRACE_BUSY;
    Rdr2_100PackPreflight info={};
    int ret=rdr2_100_pack_preflight(read_rva,ctx,major,minor,base,&info);
    if(ret!=RDR2_100_TRACE_OK)return ret;
    unsigned char pointer_bytes[8]={};
    if(read_absolute(ctx,static_cast<std::uint64_t>(
                reinterpret_cast<std::uintptr_t>(device)),
                pointer_bytes,sizeof(pointer_bytes))!=0)
        return RDR2_100_TRACE_UNMAPPED;
    if(le64(pointer_bytes)!=info.expected_vptr)
        return RDR2_100_TRACE_STALE_INSTANCE;
    unsigned char full_table[kBytes]={};
    if(read_rva(ctx,RDR2_100_PACK_VTABLE_RVA,full_table,
                sizeof(full_table))!=0)
        return RDR2_100_TRACE_UNMAPPED;
    /* Check second read to avoid racing with any modified image/vtable. */
    if(verify_full_table(full_table,base)!=RDR2_100_TRACE_OK)
        return RDR2_100_TRACE_PROFILE_MISMATCH;
    return reserve_and_install(device, reinterpret_cast<void*>(
         static_cast<std::uintptr_t>(info.expected_vptr)),
         full_table,info.expected_open,base+kRTTI,nullptr,callback,trace_context);
}

extern "C" int rdr2_100_pack_trace_detach(void* device) {
    int ready=Attached;
    if(!g_phase.compare_exchange_strong(ready,Detaching,
            std::memory_order_acq_rel,std::memory_order_acquire))
        return ready==Retired ? RDR2_100_TRACE_NOT_ATTACHED :
               (ready==Fresh ? RDR2_100_TRACE_NOT_ATTACHED :
                               RDR2_100_TRACE_BUSY);
    if(!device || device!=g_hook.device ||
       g_active.load(std::memory_order_acquire)!=0u) {
        g_phase.store(Attached,std::memory_order_release);
        return RDR2_100_TRACE_BUSY;
    }
    void* shadow=&g_hook.entries[2u];
    const bool swapped=__atomic_compare_exchange_n(
        static_cast<void**>(device), &shadow, g_hook.original_address_point,
        false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    if(!swapped) {
        /* Do not reset memory or permit another attachment if a game thread
         * or destructor changed this object's vptr unexpectedly. */
        g_phase.store(Unsafe,std::memory_order_release);
        return RDR2_100_TRACE_STALE_INSTANCE;
    }
    g_phase.store(Retired,std::memory_order_release);
    return RDR2_100_TRACE_OK;
}

extern "C" int rdr2_100_pack_trace_is_attached(void* device) {
    return device && device==g_hook.device &&
           g_phase.load(std::memory_order_acquire)==Attached;
}
extern "C" std::uint64_t rdr2_100_pack_trace_open_calls(void) {
    return g_open_count.load(std::memory_order_relaxed);
}
extern "C" std::uint32_t rdr2_100_pack_trace_active_calls(void) {
    return g_active.load(std::memory_order_acquire);
}
extern "C" int rdr2_100_pack_trace_may_unload(void) {
    /* Retired shadow can still be referenced by a previously cached call. */
    return g_phase.load(std::memory_order_acquire)==Fresh;
}

#ifdef RDR2_100_HOST_TEST
extern "C" int rdr2_100_pack_trace_host_fixture_attach(
    void* device, void* expected_vptr, Rdr2_100PackOpenFn original,
    Rdr2_100PackTraceFn callback, void* ctx) {
    if(!device || !expected_vptr || !original ||
       (reinterpret_cast<std::uintptr_t>(device)&7u))
        return RDR2_100_TRACE_BAD_ARGUMENT;
    if(__atomic_load_n(static_cast<void**>(device), __ATOMIC_ACQUIRE)!=
       expected_vptr) return RDR2_100_TRACE_STALE_INSTANCE;
    auto* original_table=static_cast<void* const*>(expected_vptr);
    if(original_table[RDR2_100_PACK_OPEN_SLOT]!=
       reinterpret_cast<void*>(original))
        return RDR2_100_TRACE_PROFILE_MISMATCH;
    unsigned char entries[kBytes]={};
    for(std::size_t i=0;i<RDR2_100_PACK_VTABLE_SLOTS;i++) {
        const auto ptr=reinterpret_cast<std::uintptr_t>(original_table[i]);
        for(unsigned b=0;b<8u;b++)
            entries[i*8u+b]=(std::uint8_t)(ptr>>(8u*b));
    }
    int status=reserve_and_install(device,expected_vptr,entries,
                   reinterpret_cast<std::uintptr_t>(original),
                   reinterpret_cast<std::uintptr_t>(original_table[-1]),
                   original_table[-2],callback,ctx);
    return status;
}
#endif
