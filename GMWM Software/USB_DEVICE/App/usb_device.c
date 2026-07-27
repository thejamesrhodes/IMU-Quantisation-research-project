/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : usb_device.c
  * @version        : v1.0_Cube
  * @brief          : This file implements the USB Device
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

/* Includes ------------------------------------------------------------------*/

#include "usb_device.h"
#include "usbd_core.h"
#include "usbd_desc.h"
#include "usbd_cdc.h"
#include "usbd_cdc_if.h"

/* USER CODE BEGIN Includes */
#include "usbd_composite.h"
#include "sheppard_config.h"

/* ---------------------------------------------------------------------------
 * Register the composite CDC + DFU class instead of the plain CDC class,
 * WITHOUT editing generated code.
 *
 * MX_USB_DEVICE_Init() below contains the generated line
 *
 *     USBD_RegisterClass(&hUsbDeviceHS, &USBD_CDC)
 *
 * which sits outside every USER CODE marker and is therefore restored by
 * CubeMX on every regeneration (TN-16 SS3.10 -- this exact class of collateral
 * damage has already cost time on this project). Redefining the symbol here,
 * after usbd_cdc.h has already declared the real object, redirects that one
 * reference and survives regeneration untouched.
 *
 * Scope is this translation unit only. usbd_cdc.c and usbd_composite.c both
 * still see the genuine USBD_CDC.
 *
 * To fall back to a plain CDC device for bisection, set
 * SHEPPARD_USB_DFU_RUNTIME to 0 in sheppard_config.h -- the composite wrapper
 * then emits a two-interface CDC-only descriptor and behaves identically to
 * the stock class.
 * ------------------------------------------------------------------------- */
#undef  USBD_CDC
#define USBD_CDC  USBD_Composite
/* USER CODE END Includes */

/* USER CODE BEGIN PV */
/* Private variables ---------------------------------------------------------*/

/* USER CODE END PV */

/* USER CODE BEGIN PFP */
/* Private function prototypes -----------------------------------------------*/

/* USER CODE END PFP */

/* USB Device Core handle declaration. */
USBD_HandleTypeDef hUsbDeviceHS;

/*
 * -- Insert your variables declaration here --
 */
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/*
 * -- Insert your external function declaration here --
 */
/* USER CODE BEGIN 1 */

/* USER CODE END 1 */

/**
  * Init USB device Library, add supported class and start the library
  * @retval None
  */
void MX_USB_DEVICE_Init(void)
{
  /* USER CODE BEGIN USB_DEVICE_Init_PreTreatment */

  /* -------------------------------------------------------------------------
   * Promote the device descriptor to a composite / IAD device.
   *
   * CubeMX generates bDeviceClass = 0x02 (Communications) because it assumes a
   * single-function CDC device. A device whose configuration contains an
   * Interface Association Descriptor MUST instead report
   *
   *     bDeviceClass    0xEF  Miscellaneous Device
   *     bDeviceSubClass 0x02  Common Class
   *     bDeviceProtocol 0x01  Interface Association Descriptor
   *
   * (USB-IF IAD ECN to USB 2.0.) With 0x02 there, a host is not obliged to
   * look for the IAD at all: Windows declines to load usbccgp, binds usbser
   * to interface 0 only, and the COM port appears but carries no data, while
   * the DFU interface is invisible. That failure is indistinguishable from a
   * broken descriptor.
   *
   * Patched here rather than edited into usbd_desc.c because that file is
   * generated and CubeMX restores it (TN-16 SS3.10).
   *
   * bcdDevice is bumped at the same time. Windows caches the driver binding
   * against USB\VID_xxxx&PID_xxxx&REV_xxxx, so a board that has previously
   * enumerated as plain CDC on 0483:5740 can otherwise come back with the
   * stale single-function binding. Changing the revision forces a fresh match.
   * ---------------------------------------------------------------------- */
  {
    extern uint8_t USBD_HS_DeviceDesc[];

    /* Cheap guard against the offsets drifting if ST re-lays-out the array. */
    if ((USBD_HS_DeviceDesc[0] == 0x12U) &&
        (USBD_HS_DeviceDesc[1] == USB_DESC_TYPE_DEVICE))
    {
      USBD_HS_DeviceDesc[4]  = 0xEFU;   /* bDeviceClass                     */
      USBD_HS_DeviceDesc[5]  = 0x02U;   /* bDeviceSubClass                  */
      USBD_HS_DeviceDesc[6]  = 0x01U;   /* bDeviceProtocol                  */
      USBD_HS_DeviceDesc[12] = 0x01U;   /* bcdDevice lo -> 2.01             */
      USBD_HS_DeviceDesc[13] = 0x02U;   /* bcdDevice hi                     */
    }
    else
    {
      Error_Handler();                  /* descriptor layout changed        */
    }
  }

  /* USER CODE END USB_DEVICE_Init_PreTreatment */

  /* Init Device Library, add supported class and start the library. */
  if (USBD_Init(&hUsbDeviceHS, &HS_Desc, DEVICE_HS) != USBD_OK)
  {
    Error_Handler();
  }
  if (USBD_RegisterClass(&hUsbDeviceHS, &USBD_CDC) != USBD_OK)
  {
    Error_Handler();
  }
  if (USBD_CDC_RegisterInterface(&hUsbDeviceHS, &USBD_Interface_fops_HS) != USBD_OK)
  {
    Error_Handler();
  }
  if (USBD_Start(&hUsbDeviceHS) != USBD_OK)
  {
    Error_Handler();
  }

  /* USER CODE BEGIN USB_DEVICE_Init_PostTreatment */

  /* USER CODE END USB_DEVICE_Init_PostTreatment */
}

/**
  * @}
  */

/**
  * @}
  */

