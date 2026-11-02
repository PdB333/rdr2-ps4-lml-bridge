/* Plugin TacHen LECTURE SEULE — validation live de la vtable fiPackfile8 (RDR2 1.00).
 *
 * But : prouver EN LIVE que les signatures statiques (REA/Ghidra) correspondent à
 * la mémoire réelle du jeu, SANS écrire un seul octet dans RDR2. On lit :
 *   - la base runtime de l'eboot (sceKernelGetModuleInfo) + la protection de chaque
 *     segment (confirme que la vtable est dans un segment read-only = RELRO),
 *   - les pointeurs de la vtable fiPackfile8, comparés aux RVA attendues.
 *
 * AUCUN hook, AUCUN sceKernelMprotect, AUCUNE écriture : conforme à la règle
 * « ne pas modifier la mémoire du jeu tant que les signatures ne sont pas validées ».
 * Trancher 11-vs-13 par comptage de trafic = étape SUIVANTE (compteur non invasif),
 * interdite tant que cette validation read-only n'a pas confirmé les adresses.
 *
 * Même chaîne de build que lml_plugin.c (crtlib.o + -lkernel, create-fself).
 * Sortie : sceKernelDebugOutText (klog) + fichier best-effort (peut être jailé).
 */
#include <stdint.h>
#include <stddef.h>
#include <orbis/libkernel.h>

/* RVA (base Ghidra 0 = p_vaddr). Code en segment_0 (r-x). vtable en segment_1 (RELRO). */
#define VT_RVA        0x066B00F8ULL  /* vtable fiPackfile8 */
#define VT_SLOTS      112
/* Slots connus (statique) -> RVA de la fonction cible, pour recoupement live. */
typedef struct { int slot; uint64_t rva; const char* name; } KnownSlot;
static const KnownSlot KNOWN[] = {
  {  2, 0x0452a480ULL, "Open" },
  { 11, 0x0452a870ULL, "Read-primitive(off 0x58)" },
  { 13, 0x0452b9d0ULL, "Read-forwarder(->+0x68)" },
  { 17, 0x0452ba90ULL, "Seek32" },
  { 18, 0x0452baa0ULL, "Seek64" },
  { 19, 0x0452be00ULL, "Close" },
  { 22, 0x0452be30ULL, "Size32" },
  { 23, 0x0452be80ULL, "Size64" },
  { 48, 0x04521a00ULL, "ReadFull(boucle +0x58)" },
};

#define LML_O_WRONLY 0x0001
#define LML_O_CREAT  0x0200
#define LML_O_APPEND 0x0008
static const char* const PROBE_LOGPATHS[] = {
  "/data/tachen/share/lml_probe.log",
  "/data/lml_probe.log",
};

/* Tampon ligne construit sans libc. */
static char g_line[256];
static size_t g_pos;
static void put_s(const char* s){ for(size_t i=0;s[i]&&g_pos<sizeof(g_line)-1;++i) g_line[g_pos++]=s[i]; }
static void put_hex(uint64_t v){
  char t[18]; int i=16; t[17]='\0';
  const char* d="0123456789abcdef";
  if(v==0){ put_s("0x0"); return; }
  while(v && i>=0){ t[i--]=d[v&0xf]; v>>=4; }
  put_s("0x"); put_s(t+i+1);
}
static void put_dec(uint64_t v){
  char t[21]; int i=20; t[20]='\0';
  if(v==0){ put_s("0"); return; }
  while(v && i>=0){ t[i--]=(char)('0'+(v%10)); v/=10; }
  put_s(t+i+1);
}
static void flush_line(void){
  g_line[g_pos++]='\n'; g_line[g_pos]='\0';
  (void)sceKernelDebugOutText(0, g_line);
  for(size_t k=0;k<sizeof(PROBE_LOGPATHS)/sizeof(PROBE_LOGPATHS[0]);++k){
    int fd=sceKernelOpen(PROBE_LOGPATHS[k], LML_O_WRONLY|LML_O_CREAT|LML_O_APPEND, 0644);
    if(fd<0) continue;
    (void)sceKernelWrite(fd, g_line, g_pos);
    (void)sceKernelClose(fd);
  }
  g_pos=0;
}
static void emit(const char* prefix, uint64_t val, int hex){
  g_pos=0; put_s(prefix); if(hex) put_hex(val); else put_dec(val); flush_line();
}

/* Exécuté par module_start (CRT -> init_array), sur un thread du jeu. */
__attribute__((constructor)) static void lml_probe_main(void){
  g_pos=0; put_s("[LML-PROBE] fiPackfile8 vtable live-check RDR2 1.00"); flush_line();

  /* 1. Base + segments de l'eboot (handle 0 = module principal). */
  OrbisKernelModuleInfo mi;
  mi.size = sizeof(mi);
  int rc = sceKernelGetModuleInfo(0, &mi);
  emit("[LML-PROBE] getModuleInfo rc=", (uint64_t)(int64_t)rc, 0);
  if(rc != 0) return;
  emit("[LML-PROBE] segmentCount=", mi.segmentCount, 0);

  uint64_t seg0 = 0;
  for(uint32_t s=0; s<mi.segmentCount && s<4; ++s){
    g_pos=0; put_s("[LML-PROBE] seg"); put_dec(s);
    put_s(" addr="); put_hex((uint64_t)mi.segmentInfo[s].address);
    put_s(" size="); put_hex(mi.segmentInfo[s].size);
    put_s(" prot="); put_hex((uint64_t)(uint32_t)mi.segmentInfo[s].prot);
    flush_line();
    if(s==0) seg0 = (uint64_t)mi.segmentInfo[s].address;
  }
  if(seg0 == 0) return;

  /* 2. VA vtable = base seg0 + RVA (PT_LOAD mappés à base+p_vaddr, p_vaddr(seg0)=0). */
  uint64_t vt = seg0 + VT_RVA;
  emit("[LML-PROBE] eboot_base=", seg0, 1);
  emit("[LML-PROBE] vtable_VA=", vt, 1);

  /* 3. Lecture des pointeurs de slots (LECTURE SEULE) + recoupement RVA. */
  const uint64_t* vp = (const uint64_t*)vt;  /* lecture directe : page mappée r-- */
  for(size_t i=0;i<sizeof(KNOWN)/sizeof(KNOWN[0]);++i){
    int sl = KNOWN[i].slot;
    uint64_t ptr = vp[sl];                   /* 8*slot, lecture seule */
    uint64_t expect = seg0 + KNOWN[i].rva;
    g_pos=0; put_s("[LML-PROBE] slot"); put_dec((uint64_t)sl);
    put_s(" ="); put_hex(ptr);
    put_s(" expect="); put_hex(expect);
    put_s((ptr==expect)?" MATCH ":" DIFF  "); put_s(KNOWN[i].name);
    flush_line();
  }
  (void)VT_SLOTS;
  g_pos=0; put_s("[LML-PROBE] done (0 ecriture dans RDR2)"); flush_line();
}
