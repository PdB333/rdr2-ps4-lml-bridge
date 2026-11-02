/* Valide un .sprx contre le VRAI validateur de conteneur de TacHen
 * (platform/native/prx-image.c : tac_prx_inspect). Compile prx-image.c tel
 * quel. Preuve que notre plugin passe le contrôle d'import de TacHen avant
 * tout essai console. Usage : validate_against_tachen <fichier.sprx>
 */
#include <stdio.h>
#include <stdlib.h>
#include "prx-image.h"

int main(int argc, char **argv) {
  if (argc != 2) { fprintf(stderr, "usage: %s <fichier.sprx>\n", argv[0]); return 2; }
  FILE *f = fopen(argv[1], "rb");
  if (!f) { perror("fopen"); return 2; }
  fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
  unsigned char *buf = malloc(n);
  if (fread(buf, 1, n, f) != (size_t)n) { fprintf(stderr, "read court\n"); return 2; }
  fclose(f);

  int platform = -1; char reason[256] = {0};
  int rc = tac_prx_inspect(buf, (size_t)n, &platform, reason, sizeof reason);
  printf("taille=%ld rc=%d platform=%d (%s)\n", n, rc, platform,
         platform == 5 ? "PS5" : "non specifie -> plateforme du jeu");
  if (rc == 0) printf("ACCEPTE par tac_prx_inspect\n");
  else printf("REJETE: %s\n", reason);
  free(buf);
  return rc == 0 ? 0 : 1;
}
