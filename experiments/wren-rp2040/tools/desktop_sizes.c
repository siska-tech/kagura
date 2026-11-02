/* Read-only ABI sizing against the existing Desktop headers; never linked. */
#include "kd_desktop.h"
#include "kdm.h"
char measured_kd_desktop[sizeof(kd_desktop)];
char measured_kdm[sizeof(kdm)];
