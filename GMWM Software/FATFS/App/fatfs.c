/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file   fatfs.c
  * @brief  Code for fatfs applications
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
#include "fatfs.h"

uint8_t retSD;    /* Return value for SD */
char SDPath[4];   /* SD logical drive path */
FATFS SDFatFS;    /* File system object for SD logical drive */
FIL SDFile;       /* File object for SD */

/* USER CODE BEGIN Variables */

/* USER CODE END Variables */

void MX_FATFS_Init(void)
{
  /*## FatFS: Link the SD driver ###########################*/
  retSD = FATFS_LinkDriver(&SD_Driver, SDPath);

  /* USER CODE BEGIN Init */
  /* additional user code for init */
  /* USER CODE END Init */
}

/**
  * @brief  Gets Time from RTC
  * @param  None
  * @retval Time in DWORD
  */
DWORD get_fattime(void)
{
  /* USER CODE BEGIN get_fattime */
	  extern RTC_HandleTypeDef hrtc;
	  RTC_TimeTypeDef t; RTC_DateTypeDef d;
	  HAL_RTC_GetTime(&hrtc, &t, RTC_FORMAT_BIN);
	  HAL_RTC_GetDate(&hrtc, &d, RTC_FORMAT_BIN);   /* must follow GetTime */
	  return ((DWORD)(2000 + d.Year - 1980) << 25)
	       | ((DWORD)d.Month << 21)
	       | ((DWORD)d.Date  << 16)
	       | ((DWORD)t.Hours << 11)
	       | ((DWORD)t.Minutes << 5)
	       | ((DWORD)t.Seconds >> 1);
  /* USER CODE END get_fattime */
}

/* USER CODE BEGIN Application */

/* USER CODE END Application */
