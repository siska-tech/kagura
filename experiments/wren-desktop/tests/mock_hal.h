#ifndef WD_MOCK_HAL_H
#define WD_MOCK_HAL_H
#include "ui.h"
typedef enum { MOCK_OK,MOCK_WRITE,MOCK_DONE,MOCK_FENCE,MOCK_ERROR,MOCK_COMMIT,MOCK_ABI } MockFailure;
void mock_reset(void);
void mock_failure(MockFailure kind);
void mock_failure_when_owned(MockFailure kind);
void mock_reenter(bool enable);
unsigned mock_reentry_rejections(void);
unsigned mock_writes(void);
unsigned mock_fences(void);
uint8_t mock_byte(unsigned address);
uint32_t mock_crc(unsigned length);
#endif
