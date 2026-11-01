// SPDX-License-Identifier: Apache-2.0
#include "profile.h"
void sf_profile_add(SfProfile *p,uint32_t us) {
    p->samples[p->count%256]=us;p->count++;p->sum+=us;if(us>p->max)p->max=us;
}
uint32_t sf_profile_p95(const SfProfile *p) {
    uint32_t sorted[256];unsigned n=p->count<256?p->count:256;if(!n)return 0;
    for(unsigned i=0;i<n;i++)sorted[i]=p->samples[i];
    for(unsigned i=1;i<n;i++) { uint32_t v=sorted[i];unsigned j=i;
        while(j && sorted[j-1]>v) { sorted[j]=sorted[j-1];j--; }sorted[j]=v;
    }
    return sorted[(n*95+99)/100-1];
}
