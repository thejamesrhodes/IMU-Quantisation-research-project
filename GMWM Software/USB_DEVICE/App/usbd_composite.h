/**
  ******************************************************************************
  * @file    usbd_composite.h
  * @brief   Composite USB device class: CDC ACM + DFU run-time interface.
  *
  * Presents three interfaces on one USB-C connector:
  *
  *   0  CDC Communications  |  grouped by an Interface Association
  *   1  CDC Data            |  Descriptor so Windows loads usbccgp + usbser
  *   2  DFU run-time        (class 0xFE, subclass 0x01, protocol 0x01)
  *
  * The DFU interface has no endpoints and implements only the run-time subset
  * of DFU 1.1: DFU_DETACH, DFU_GETSTATUS, DFU_GETSTATE. It performs no
  * flashing. On DFU_DETACH it calls USBD_Composite_DfuDetach(), which the
  * application overrides to reboot into the loader.
  *
  * WHY A HAND-WRITTEN WRAPPER RATHER THAN ST's COMPOSITE BUILDER
  *   USE_USBD_COMPOSITE is not defined in this project, so the core runs
  *   single-class with classId fixed at 0. This driver registers as that one
  *   class, serves its own configuration descriptor, and forwards every CDC
  *   endpoint and control event to the stock USBD_CDC driver. USBD_CDC keeps
  *   ownership of pClassDataCmsit[0] and pClassData, so CDC_Transmit_HS,
  *   USBD_CDC_SetRxBuffer and USBD_CDC_ReceivePacket all keep working with no
  *   changes -- including the re-arm pair in CDC_Receive_HS that TN-16 SS7.2
  *   warns must never be deleted.
  ******************************************************************************
  */

#ifndef USBD_COMPOSITE_H
#define USBD_COMPOSITE_H

#include "usbd_def.h"

#ifdef __cplusplus
extern "C" {
#endif

/** The class driver to hand to USBD_RegisterClass(). */
extern USBD_ClassTypeDef USBD_Composite;

/**
  * @brief  Main-loop housekeeping for the class driver.
  *         Call every iteration. Currently: dispatches a pending DFU_DETACH
  *         out of interrupt context.
  */
void usbd_composite_task(void);

/**
  * @brief  Called once, from the main loop, after the host issues DFU_DETACH
  *         on interface 2.
  *
  *         Default implementation is empty. boot_ctrl.c overrides it to write
  *         the loader request magic and schedule a reset. Declared __weak so
  *         that a build with SHEPPARD_USB_DFU_RUNTIME enabled but no loader
  *         still links and simply ignores the request.
  */
void USBD_Composite_DfuDetach(void);

/**
  * @brief  Current DFU run-time state (0 = appIDLE, 1 = appDETACH).
  *         Diagnostic only.
  */
uint8_t usbd_composite_dfu_state(void);

#ifdef __cplusplus
}
#endif

#endif /* USBD_COMPOSITE_H */
