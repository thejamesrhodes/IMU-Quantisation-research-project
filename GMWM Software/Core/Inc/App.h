#ifndef APP_H
#define APP_H

#include "main.h"

/* Call once from main.c, USER CODE BEGIN 2 (after all MX_*_Init() calls) */
void App_Init(void);

/* Call every iteration from main.c, USER CODE BEGIN WHILE (inside while(1)) */
void App_Run(void);

#endif /* APP_H */
