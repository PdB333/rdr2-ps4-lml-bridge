# OBSOLETE -- recette PS5 (sie-ps5 + make_fself), ABANDONNEE.
#
# Le module PS5 produit ici passait le controle de conteneur de TacHen mais etait
# REJETE par le loader kernel dans le process PS4 de RDR2 (runtime.log :
# 0x80020016 EINVAL, module_start jamais execute). RDR2 est un titre PS4 : le
# format attendu est un PRX PS4 OpenOrbis.
#
# >>> BUILD CANONIQUE VERIFIE : plugin/tachen/build_ps4.ps1 <<<
#     (clang --target=x86_64-pc-freebsd12-elf + crtlib.o + create-fself)
#
# Ce Makefile reference aussi l'ancien lml_plugin.c (module_start fait main) ;
# la source actuelle delegue le scaffolding a crtlib.o et ne compilera PAS tel
# quel ici. Conserve uniquement comme trace de l'impasse PS5.

ifndef PS5_PAYLOAD_SDK
    $(error PS5_PAYLOAD_SDK est indefini : exporter la racine du ps5-payload-sdk)
endif

PATCH_ETYPE ?= python3 patch_etype.py
ELF2SELF    ?= python3 $(PS5_PAYLOAD_SDK)/samples/install_app/make_fself.py

CC       ?= clang
CFLAGS   := -target x86_64-sie-ps5 -isysroot $(PS5_PAYLOAD_SDK) \
            -isystem $(PS5_PAYLOAD_SDK)/target/include \
            -fno-stack-protector -fno-plt -femulated-tls -fPIC -Wall -g
LD       ?= ld.lld
LDFLAGS  := -m elf_x86_64_fbsd --eh-frame-hdr --hash-style=sysv --build-id=uuid \
            --unresolved-symbols=report-all -z now -z start-stop-visibility=hidden \
            -z rodynamic -z common-page-size=0x4000 -z max-page-size=0x4000 \
            --default-script $(PS5_PAYLOAD_SDK)/target/lib/prx.script --shared \
            -L $(PS5_PAYLOAD_SDK)/target/lib
LDLIBS   := -l:crti.o -l:crtbeginS.o lml_plugin.o -lc -lkernel_web \
            -lSceLibcInternal -lc_stub_weak -lkernel_stub_weak -l:crtendS.o -l:crtn.o

PRX  := lml_plugin.prx
SPRX := lml_plugin.sprx

all: $(SPRX)

lml_plugin.o: lml_plugin.c
	$(CC) $(CFLAGS) -c -o $@ $<

$(PRX): lml_plugin.o
	$(LD) $(LDFLAGS) -o $@ $(LDLIBS)
	$(PATCH_ETYPE) $@

$(SPRX): $(PRX)
	$(ELF2SELF) --ptype fake $< $@

clean:
	rm -f lml_plugin.o $(PRX) $(SPRX)

.PHONY: all clean
