#include "rdr2_100_registry.h"
#include <limits.h>
static uint64_t u64le(const unsigned char b[8]) {
    uint64_t value=0;
    unsigned i;
    for(i=0;i<8u;i++)value |= ((uint64_t)b[i])<<(8u*i);
    return value;
}
int rdr2_100_find_pack_instances(Rdr2_100ReadAbsolute read, void *context,
    uint32_t major, uint32_t minor, uint64_t base, uint32_t start,
    uint32_t count, uint64_t *out, size_t capacity, size_t *out_count) {
    uint32_t i;
    size_t found=0;
    unsigned char bytes[8];
    if(out_count)*out_count=0;
    /* Patch must be selected independently. This is a PS4 1.00 RVA. */
    if(major!=1u || minor!=0u)return RDR2_100_REGISTRY_UNSUPPORTED_VERSION;
    if(!read || !out_count || (capacity && !out) ||
       !count || count>RDR2_100_REGISTRY_BATCH_LIMIT ||
       start>65535u || count>65536u-start ||
       base>UINT64_MAX-(RDR2_100_REGISTRY_RVA+65536u*8u) ||
       base>UINT64_MAX-RDR2_100_PACK_VPTR_RVA)
        return RDR2_100_REGISTRY_BAD_ARGUMENT;
    for(i=0;i<count;i++){
        const uint32_t slot=start+i;
        const uint64_t address=base+RDR2_100_REGISTRY_RVA+(uint64_t)slot*8u;
        uint64_t object;
        if(read(context,address,bytes,8u)!=0)
            return RDR2_100_REGISTRY_UNMAPPED;
        object=u64le(bytes);
        if(!object || (object&7u)!=0u || object>UINT64_MAX-16u)
            continue;
        if(read(context,object,bytes,8u)!=0 ||
           u64le(bytes)!=base+RDR2_100_PACK_VPTR_RVA)
            continue;
        if(read(context,object+8u,bytes,2u)!=0 ||
           (unsigned)bytes[0] + ((unsigned)bytes[1]<<8u)!=slot)
            continue;
        if(found<capacity && out)out[found]=object;
        ++found;
    }
    *out_count=found;
    return found>capacity ? RDR2_100_REGISTRY_TRUNCATED :
                           RDR2_100_REGISTRY_OK;
}
