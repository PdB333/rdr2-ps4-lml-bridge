# Build du plugin TacHen « preuve de vie » LML (RDR2 PS4 1.00).
#
# ATTENTION : sous Windows, le chemin canonique VERIFIE est build.cmd, PAS ce
# Makefile. Les wrappers prospero-clang/-lld du SDK ne conviennent pas pour un
# objet partage (scripts Linux ; prospero-lld.exe force -pie, incompatible
# --shared). build.cmd appelle clang puis ld.lld directement, patche e_type en
# ET_SCE_DYNAMIC (0xfe18), puis make_fself --ptype fake.
#
# Cette cible Make est conservee pour un hote Linux ou prospero.mk fonctionne,
# mais elle n'a PAS ete validee et ne fait pas le patch e_type ni le lien SCE
# explicite. Reporter la recette de build.cmd si on veut la fiabiliser.

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
