/* ANALYSIS ONLY: deliberately no RP2040 boot2/vector image or upload format. */
ENTRY(_start)
MEMORY { FLASH(rx) : ORIGIN = 0x10000000, LENGTH = 2M
         RAM(rwx) : ORIGIN = 0x20000000, LENGTH = 264K }
SECTIONS {
 .text : { *(.text*) *(.rodata*) } > FLASH
 .ARM.exidx : { *(.ARM.exidx*) } > FLASH
 .data : { *(.data*) } > RAM AT > FLASH
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } > RAM
 /DISCARD/ : { *(.comment) *(.note*) }
}
