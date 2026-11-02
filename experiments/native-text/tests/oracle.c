/* SPDX-License-Identifier: Apache-2.0 */
#include "kj_text.h"
#include <stdio.h>
#include <string.h>
int main(int argc,char **argv) {
    if (argc==2 && !strcmp(argv[1],"glyphs")) {
        for (unsigned i=0;i<kj_misaki8.count;i++) {
            const uint8_t *p=kj_misaki8.data+8+i*10; unsigned cp=p[0]|((unsigned)p[1]<<8);
            kj_glyph g=kj_lookup(&kj_misaki8,cp);
            printf("%04x ",cp); for (unsigned j=0;j<8;j++) printf("%02x",g.rows[j]); puts("");
        }
        return 0;
    }
    char line[128];
    while (fgets(line,sizeof line,stdin)) {
        uint8_t bytes[32]; size_t n=0;
        for (size_t i=0;line[i] && line[i]!='\n' && n<32;i+=2) {
            unsigned b; if (sscanf(line+i,"%2x",&b)!=1) return 2; bytes[n++]=(uint8_t)b;
        }
        kj_decoded d=kj_utf8_next(bytes,n); printf("%u %u %x\n",d.valid,d.consumed,(unsigned)d.scalar);
    }
    return 0;
}
