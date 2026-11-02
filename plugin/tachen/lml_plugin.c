/* Plugin TacHen minimal « preuve de vie » pour RDR2 PS4 1.00 (CUSA08519).
 *
 * But : prouver que NOTRE code s'exécute dans le process du jeu via le chargeur
 * TacHen, SANS toucher la mémoire de RDR2. Build = PRX PS4 (OpenOrbis), car
 * RDR2 est un titre PS4 ; un module PS5 (sie-ps5) est rejeté par le loader
 * kernel (EINVAL 0x80020016). Voir build_ps4.ps1.
 *
 * Scaffolding fourni par le CRT OpenOrbis (crtlib.o), PAS fait main : c'est le
 * CRT qui fournit module_start / module_stop / _init / _fini, la section
 * .data.sce_module_param et le parcours de .init_array. Motif : un
 * .data.sce_module_param écrit à la main faisait dédoubler par create-fself le
 * PT_LOAD inscriptible (deux segments identiques superposés), ce qui faisait
 * échouer le contrôle de conteneur de TacHen (tac_prx_inspect, overlap).
 * crtlib.o produit une disposition propre (cf. orbis/build_loader_smoke.ps1,
 * seul PRX OpenOrbis sans duplicata). Le module_start du CRT parcourt
 * __init_array_start/end : notre constructeur ci-dessous s'y exécute.
 *
 * Imports : UNIQUEMENT libkernel (sceKernel*), aucune libc (la libc rajoute du
 * .bss qui relance le dédoublement).
 *
 * Preuve : best-effort sur deux canaux indépendants du sandbox —
 *   1) sceKernelDebugOutText (sortie debug/klog),
 *   2) fichier /data/lml_bridge_spike.log (peut être jailé dans le sandbox).
 * Le juge primaire reste le runtime.log de TacHen (résultat de l'initialiseur).
 *
 * Quand le spike sera validé en jeu, le point HOOK appellera
 *   rdr2_100_packfile_hooks_arm(). Interdit tant que les signatures fiPackfile8
 *   ne sont pas validées en live.
 */
#include <stdint.h>
#include <stddef.h>
#include <orbis/libkernel.h>

/* Drapeaux open() FreeBSD (cf. SDK include/fcntl.h + bits/fcntl.h). */
#define LML_O_WRONLY 0x0001
#define LML_O_CREAT  0x0200
#define LML_O_APPEND 0x0008
/* Chemins candidats, best-effort. Le FTP TacHen anonyme (port 2122) est jailé
 * sur le dossier share : on vise aussi share + share/payloads pour une relecture
 * directe. L'un au moins doit passer le sandbox du jeu ET être exposé. */
static const char* const LML_LOGPATHS[] = {
  "/data/tachen/share/lml_bridge_spike.log",
  "/data/tachen/share/payloads/lml_bridge_spike.log",
  "/data/lml_bridge_spike.log",
};

/* Longueur d'une C-string, sans libc. */
static size_t
lml_len(const char* s) {
  size_t n = 0;
  while (s[n]) {
    ++n;
  }
  return n;
}

/* Canal 1 : sortie debug console (indépendante du système de fichiers). */
static void
lml_debug(const char* text) {
  (void)sceKernelDebugOutText(0, text);
}

/* Canal 2 : marqueur fichier, best-effort (peut échouer en sandbox jailé).
 * I/O via libkernel uniquement : préfixe horodaté brut (process time) suivi du
 * message, sans snprintf ni libc. */
static void
lml_file(const char* msg) {
  /* Horodatage brut : « [LML] <processtime> » en décimal, sans libc. */
  uint64_t t = sceKernelGetProcessTime();
  char num[24];
  int i = (int)sizeof(num);
  num[--i] = ' ';
  if (t == 0) {
    num[--i] = '0';
  } else {
    while (t && i > 0) {
      num[--i] = (char)('0' + (int)(t % 10));
      t /= 10;
    }
  }
  const char* tag = "[LML] ";
  for (size_t k = 0; k < sizeof(LML_LOGPATHS) / sizeof(LML_LOGPATHS[0]); ++k) {
    int fd = sceKernelOpen(LML_LOGPATHS[k],
                           LML_O_WRONLY | LML_O_CREAT | LML_O_APPEND, 0644);
    if (fd < 0) {
      continue;
    }
    (void)sceKernelWrite(fd, tag, lml_len(tag));
    (void)sceKernelWrite(fd, num + i, sizeof(num) - (size_t)i);
    (void)sceKernelWrite(fd, msg, lml_len(msg));
    (void)sceKernelWrite(fd, "\n", 1);
    (void)sceKernelClose(fd);
  }
}

/* Exécuté par le module_start du CRT via .init_array, sur un thread du jeu. */
__attribute__((constructor)) static void
lml_proof_of_life(void) {
  lml_debug("[LML] module_start: notre code tourne dans le process RDR2 1.00\n");
  lml_file("module_start: notre code tourne dans le process RDR2 1.00");

  /* HOOK (plus tard, après validation live des signatures fiPackfile8) :
   *   #include "../../runtime/rdr2_100_packfile_hooks.h"
   *   rdr2_100_packfile_hooks_arm();
   * Interdit tant que le détour n'est pas validé en live. */
}
