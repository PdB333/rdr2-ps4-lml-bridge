/* Plugin TacHen minimal « preuve de vie » pour RDR2 PS4 1.00 (CUSA08519).
 *
 * But du spike : prouver que NOTRE code s'exécute dans le process du jeu via le
 * chargeur de plugins TacHen, AVANT de greffer quoi que ce soit sur la mémoire
 * du jeu. Ce module ne touche PAS la mémoire de RDR2 : il écrit seulement un
 * marqueur dans /data (stockage utilisateur) pour confirmer le chargement.
 *
 * Entrée : convention de module SCE PRX (comme sur PS4/PS5). TacHen appelle
 *   module_start sur un pthread du jeu ; un résultat non nul = échec de charge.
 *   La paire module_stop est appelée au déchargement.
 *
 * Imports (open/write/close, clock_gettime) : résolus par le chargeur TacHen
 *   (libelfldr + sceKernelLoadStartModule) contre libSceLibcInternal, PAS via
 *   payload_args/dlsym. C'est pour ça qu'on compile un vrai SELF à stubs
 *   d'import et non un payload autonome ELF_RPC.
 *
 * Quand le spike sera validé, le point marqué HOOK ci-dessous appellera
 *   rdr2_100_packfile_hooks (armement du détour fiPackfile8). Rien de tout cela
 *   n'est fait ici : la mémoire du jeu reste intacte tant que les signatures
 *   ne sont pas validées en live.
 */
#include <fcntl.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define LML_TAG      "[LML]"
#define LML_LOGPATH  "/data/lml_bridge_spike.log"

/* Ecrit une ligne horodatée dans le marqueur. Best-effort : si /data n'est pas
 * accessible, on échoue silencieusement (le module ne doit pas planter le jeu).
 */
static void
lml_log(const char* msg) {
  int fd = open(LML_LOGPATH, O_WRONLY | O_CREAT | O_APPEND, 0644);
  if (fd < 0) {
    return;
  }

  struct timespec ts;
  ts.tv_sec = 0;
  ts.tv_nsec = 0;
  clock_gettime(CLOCK_REALTIME, &ts);

  char line[256];
  int n = snprintf(line, sizeof(line), "%s %lld.%03ld %s\n", LML_TAG,
                   (long long)ts.tv_sec, ts.tv_nsec / 1000000L, msg);
  if (n > 0) {
    if (n > (int)sizeof(line)) {
      n = (int)sizeof(line);
    }
    (void)write(fd, line, (size_t)n);
  }
  close(fd);
}

/* Entrée du module. Exécutée par TacHen sur un thread du jeu. */
int
module_start(size_t argc, const void* argv) {
  (void)argc;
  (void)argv;

  lml_log("module_start: notre code tourne dans le process RDR2 1.00");

  /* HOOK (plus tard, apres validation live des signatures fiPackfile8) :
   *   #include "../../runtime/rdr2_100_packfile_hooks.h"
   *   rdr2_100_packfile_hooks_arm();
   * Interdit tant que le detour n'est pas valide en live. */

  return 0; /* succes : TacHen garde le module resident */
}

/* Sortie du module (déchargement par TacHen). */
int
module_stop(size_t argc, const void* argv) {
  (void)argc;
  (void)argv;

  lml_log("module_stop: dechargement du plugin");
  return 0;
}
