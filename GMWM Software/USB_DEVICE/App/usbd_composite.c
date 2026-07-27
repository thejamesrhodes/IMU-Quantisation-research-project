/**
  ******************************************************************************
  * @file    usbd_composite.c
  * @brief   Composite USB device class: CDC ACM + DFU run-time interface.
  ******************************************************************************
  */

#include "usbd_composite.h"
#include "usbd_cdc.h"
#include "usbd_ctlreq.h"
#include "usbd_ioreq.h"
#include "sheppard_config.h"

/* ==========================================================================
 * Descriptor constants
 * ========================================================================== */

#ifndef USBD_MAX_POWER
#define USBD_MAX_POWER                  0x32U     /* 100 mA */
#endif

#define USB_DESC_TYPE_IAD               0x0BU
#define USB_DESC_TYPE_DFU_FUNCTIONAL    0x21U

#define USB_CLASS_APPLICATION_SPECIFIC  0xFEU
#define USB_SUBCLASS_DFU                0x01U
#define USB_PROTOCOL_DFU_RUNTIME        0x01U

/* DFU 1.1 functional descriptor bmAttributes */
#define DFU_ATTR_WILL_DETACH            0x08U
#define DFU_ATTR_MANIFEST_TOLERANT      0x04U
#define DFU_ATTR_CAN_UPLOAD             0x02U
#define DFU_ATTR_CAN_DOWNLOAD           0x01U

/* bitWillDetach set: the device resets itself after acknowledging DFU_DETACH,
   so the host must not issue a bus reset and wait. That is exactly what
   boot_ctrl does. ManifestationTolerant cleared: the loader reboots after a
   download rather than returning to dfuIDLE. */
#define DFU_RT_ATTRIBUTES  (DFU_ATTR_WILL_DETACH | \
                            DFU_ATTR_CAN_UPLOAD  | \
                            DFU_ATTR_CAN_DOWNLOAD)

/* DFU class requests */
#define DFU_REQ_DETACH                  0x00U
#define DFU_REQ_DNLOAD                  0x01U
#define DFU_REQ_UPLOAD                  0x02U
#define DFU_REQ_GETSTATUS               0x03U
#define DFU_REQ_CLRSTATUS               0x04U
#define DFU_REQ_GETSTATE                0x05U
#define DFU_REQ_ABORT                   0x06U

/* DFU run-time states */
#define DFU_STATE_APP_IDLE              0x00U
#define DFU_STATE_APP_DETACH            0x01U

/* Configuration descriptor total length. Verified against sizeof() below --
   a mismatch here makes the device enumerate as a corrupt descriptor, which
   presents on Windows as "Device Descriptor Request Failed" with no clue. */
#if SHEPPARD_USB_DFU_RUNTIME
#define COMPOSITE_CFG_DESC_SIZE         93U
#define COMPOSITE_NUM_INTERFACES        3U
#else
#define COMPOSITE_CFG_DESC_SIZE         75U
#define COMPOSITE_NUM_INTERFACES        2U
#endif

#if (USBD_SELF_POWERED == 1U)
#define COMPOSITE_BMATTRIBUTES          0xC0U
#else
#define COMPOSITE_BMATTRIBUTES          0x80U
#endif

/* ==========================================================================
 * Module state
 * ========================================================================== */

static volatile uint8_t s_dfu_state    = DFU_STATE_APP_IDLE;
static volatile uint8_t s_detach_armed = 0U;   /* set in USB IRQ, consumed in main */

/* ==========================================================================
 * Configuration descriptors
 *
 * Layout (both speeds):
 *    9  configuration
 *    8  interface association (interfaces 0-1, CDC function)
 *    9  interface 0 - CDC Communications
 *    5  CDC header functional
 *    5  CDC call management functional
 *    4  CDC ACM functional
 *    5  CDC union functional
 *    7  endpoint 0x82 IN, interrupt  (notification)
 *    9  interface 1 - CDC Data
 *    7  endpoint 0x01 OUT, bulk
 *    7  endpoint 0x81 IN,  bulk
 *    9  interface 2 - DFU run-time            } omitted when
 *    9  DFU functional                        } SHEPPARD_USB_DFU_RUNTIME == 0
 *
 * Endpoint addresses and packet sizes are taken from usbd_cdc.h so that they
 * cannot drift away from what USBD_CDC_Init() actually opens.
 * ========================================================================== */

#define COMPOSITE_CDC_BLOCK(bulk_mps, cmd_binterval)                             \
  /* --- IAD: tells the host that interfaces 0 and 1 are one CDC function.  */  \
  /*     Without it Windows binds usbser to interface 0 only and the data   */  \
  /*     interface is left unclaimed, so the COM port opens but moves no    */  \
  /*     bytes.                                                             */  \
  0x08, USB_DESC_TYPE_IAD,                                                       \
  SHEPPARD_ITF_CDC_COMM,          /* bFirstInterface  */                         \
  0x02,                           /* bInterfaceCount  */                         \
  0x02,                           /* bFunctionClass    = CDC        */           \
  0x02,                           /* bFunctionSubClass = ACM        */           \
  0x01,                           /* bFunctionProtocol = AT cmds    */           \
  0x00,                           /* iFunction */                                \
                                                                                 \
  /* --- Interface 0: CDC Communications --------------------------------- */   \
  0x09, USB_DESC_TYPE_INTERFACE,                                                 \
  SHEPPARD_ITF_CDC_COMM, 0x00, 0x01,                                             \
  0x02, 0x02, 0x01, 0x00,                                                        \
                                                                                 \
  /* Header functional */                                                        \
  0x05, 0x24, 0x00, 0x10, 0x01,                                                  \
  /* Call management functional: data interface = 1 */                           \
  0x05, 0x24, 0x01, 0x00, SHEPPARD_ITF_CDC_DATA,                                 \
  /* ACM functional: supports Set_Line_Coding etc. */                            \
  0x04, 0x24, 0x02, 0x02,                                                        \
  /* Union functional: master 0, slave 1 */                                      \
  0x05, 0x24, 0x06, SHEPPARD_ITF_CDC_COMM, SHEPPARD_ITF_CDC_DATA,                \
                                                                                 \
  /* Notification endpoint */                                                    \
  0x07, USB_DESC_TYPE_ENDPOINT, CDC_CMD_EP, 0x03,                                \
  LOBYTE(CDC_CMD_PACKET_SIZE), HIBYTE(CDC_CMD_PACKET_SIZE), (cmd_binterval),     \
                                                                                 \
  /* --- Interface 1: CDC Data ------------------------------------------- */   \
  0x09, USB_DESC_TYPE_INTERFACE,                                                 \
  SHEPPARD_ITF_CDC_DATA, 0x00, 0x02,                                             \
  0x0A, 0x00, 0x00, 0x00,                                                        \
                                                                                 \
  0x07, USB_DESC_TYPE_ENDPOINT, CDC_OUT_EP, 0x02,                                \
  LOBYTE(bulk_mps), HIBYTE(bulk_mps), 0x00,                                      \
                                                                                 \
  0x07, USB_DESC_TYPE_ENDPOINT, CDC_IN_EP, 0x02,                                 \
  LOBYTE(bulk_mps), HIBYTE(bulk_mps), 0x00

#if SHEPPARD_USB_DFU_RUNTIME
#define COMPOSITE_DFU_BLOCK                                                      \
  /* --- Interface 2: DFU run-time, no endpoints ------------------------- */   \
  0x09, USB_DESC_TYPE_INTERFACE,                                                 \
  SHEPPARD_ITF_DFU, 0x00, 0x00,                                                  \
  USB_CLASS_APPLICATION_SPECIFIC, USB_SUBCLASS_DFU, USB_PROTOCOL_DFU_RUNTIME,    \
  0x00,                           /* iInterface: none.                     */   \
                                  /* A string here would be nicer in Device*/   \
                                  /* Manager but usbd_desc.c is CubeMX-    */   \
                                  /* generated and the string table would  */   \
                                  /* be reverted on regeneration.          */   \
                                                                                 \
  /* DFU functional descriptor */                                               \
  0x09, USB_DESC_TYPE_DFU_FUNCTIONAL,                                            \
  DFU_RT_ATTRIBUTES,                                                             \
  LOBYTE(SHEPPARD_DFU_DETACH_TIMEOUT_MS), HIBYTE(SHEPPARD_DFU_DETACH_TIMEOUT_MS),\
  LOBYTE(SHEPPARD_DFU_TRANSFER_SIZE),     HIBYTE(SHEPPARD_DFU_TRANSFER_SIZE),    \
  LOBYTE(SHEPPARD_DFU_BCD_VERSION),       HIBYTE(SHEPPARD_DFU_BCD_VERSION)
#else
#define COMPOSITE_DFU_BLOCK 0x00 /* placeholder, never reached */
#endif

/* ---- high speed ---------------------------------------------------------- */

__ALIGN_BEGIN static uint8_t s_cfg_desc_hs[COMPOSITE_CFG_DESC_SIZE] __ALIGN_END = {
  0x09, USB_DESC_TYPE_CONFIGURATION,
  LOBYTE(COMPOSITE_CFG_DESC_SIZE), HIBYTE(COMPOSITE_CFG_DESC_SIZE),
  COMPOSITE_NUM_INTERFACES,
  0x01,                           /* bConfigurationValue */
  0x00,                           /* iConfiguration      */
  COMPOSITE_BMATTRIBUTES,
  USBD_MAX_POWER,

  COMPOSITE_CDC_BLOCK(CDC_DATA_HS_MAX_PACKET_SIZE, CDC_HS_BINTERVAL)
#if SHEPPARD_USB_DFU_RUNTIME
  , COMPOSITE_DFU_BLOCK
#endif
};

/* ---- full speed ---------------------------------------------------------- */

__ALIGN_BEGIN static uint8_t s_cfg_desc_fs[COMPOSITE_CFG_DESC_SIZE] __ALIGN_END = {
  0x09, USB_DESC_TYPE_CONFIGURATION,
  LOBYTE(COMPOSITE_CFG_DESC_SIZE), HIBYTE(COMPOSITE_CFG_DESC_SIZE),
  COMPOSITE_NUM_INTERFACES,
  0x01,
  0x00,
  COMPOSITE_BMATTRIBUTES,
  USBD_MAX_POWER,

  COMPOSITE_CDC_BLOCK(CDC_DATA_FS_MAX_PACKET_SIZE, CDC_FS_BINTERVAL)
#if SHEPPARD_USB_DFU_RUNTIME
  , COMPOSITE_DFU_BLOCK
#endif
};

/* Compile-time check that the hand-computed wTotalLength matches reality.
   If this line fails to compile, the descriptor body changed and
   COMPOSITE_CFG_DESC_SIZE was not updated. Fix the constant, do not widen
   the array. */
typedef char composite_cfg_size_check[
  (sizeof(s_cfg_desc_hs) == COMPOSITE_CFG_DESC_SIZE) ? 1 : -1];

/* ---- other speed --------------------------------------------------------- */

__ALIGN_BEGIN static uint8_t s_cfg_desc_other[COMPOSITE_CFG_DESC_SIZE] __ALIGN_END;

/* ---- device qualifier ---------------------------------------------------- */

__ALIGN_BEGIN static uint8_t s_device_qualifier[USB_LEN_DEV_QUALIFIER_DESC] __ALIGN_END = {
  USB_LEN_DEV_QUALIFIER_DESC,
  USB_DESC_TYPE_DEVICE_QUALIFIER,
  0x00, 0x02,                     /* bcdUSB 2.00        */
  0xEF,                           /* bDeviceClass    = Miscellaneous  */
  0x02,                           /* bDeviceSubClass = Common Class   */
  0x01,                           /* bDeviceProtocol = IAD            */
  0x40,                           /* bMaxPacketSize0                  */
  0x01,                           /* bNumConfigurations               */
  0x00,
};

/* ==========================================================================
 * DFU run-time request handling
 * ========================================================================== */

#if SHEPPARD_USB_DFU_RUNTIME

static uint8_t dfu_rt_setup(USBD_HandleTypeDef *pdev, USBD_SetupReqTypedef *req)
{
  static __ALIGN_BEGIN uint8_t status[6] __ALIGN_END;
  uint16_t len;

  switch (req->bmRequest & USB_REQ_TYPE_MASK)
  {
    case USB_REQ_TYPE_CLASS:
      switch (req->bRequest)
      {
        case DFU_REQ_DETACH:
          /* Acknowledge first, reboot later. Resetting inside the setup
             handler would abort the status stage and the host would report
             a failed control transfer even though the detach worked. */
          if (s_dfu_state == DFU_STATE_APP_IDLE)
          {
            s_dfu_state    = DFU_STATE_APP_DETACH;
            s_detach_armed = 1U;
          }
          (void)USBD_CtlSendStatus(pdev);
          break;

        case DFU_REQ_GETSTATUS:
          status[0] = 0x00U;                      /* bStatus = OK           */
          status[1] = 0x00U;                      /* bwPollTimeout[0]       */
          status[2] = 0x00U;                      /* bwPollTimeout[1]       */
          status[3] = 0x00U;                      /* bwPollTimeout[2]       */
          status[4] = s_dfu_state;                /* bState                 */
          status[5] = 0x00U;                      /* iString                */
          len = (req->wLength < 6U) ? req->wLength : 6U;
          (void)USBD_CtlSendData(pdev, status, len);
          break;

        case DFU_REQ_GETSTATE:
          status[0] = s_dfu_state;
          (void)USBD_CtlSendData(pdev, status, 1U);
          break;

        /* DNLOAD, UPLOAD, CLRSTATUS and ABORT are DFU-mode only. Stalling
           them is what tells a host that this is a run-time interface. */
        default:
          USBD_CtlError(pdev, req);
          return (uint8_t)USBD_FAIL;
      }
      break;

    case USB_REQ_TYPE_STANDARD:
      switch (req->bRequest)
      {
        case USB_REQ_GET_STATUS:
          if (pdev->dev_state == USBD_STATE_CONFIGURED)
          {
            status[0] = 0x00U;
            status[1] = 0x00U;
            (void)USBD_CtlSendData(pdev, status, 2U);
          }
          else
          {
            USBD_CtlError(pdev, req);
            return (uint8_t)USBD_FAIL;
          }
          break;

        case USB_REQ_GET_INTERFACE:
          if (pdev->dev_state == USBD_STATE_CONFIGURED)
          {
            status[0] = 0x00U;                    /* only alt setting 0 exists */
            (void)USBD_CtlSendData(pdev, status, 1U);
          }
          else
          {
            USBD_CtlError(pdev, req);
            return (uint8_t)USBD_FAIL;
          }
          break;

        case USB_REQ_SET_INTERFACE:
          if ((pdev->dev_state == USBD_STATE_CONFIGURED) &&
              (LOBYTE(req->wValue) == 0x00U))
          {
            (void)USBD_CtlSendStatus(pdev);
          }
          else
          {
            USBD_CtlError(pdev, req);
            return (uint8_t)USBD_FAIL;
          }
          break;

        case USB_REQ_CLEAR_FEATURE:
          (void)USBD_CtlSendStatus(pdev);
          break;

        default:
          USBD_CtlError(pdev, req);
          return (uint8_t)USBD_FAIL;
      }
      break;

    default:
      USBD_CtlError(pdev, req);
      return (uint8_t)USBD_FAIL;
  }

  return (uint8_t)USBD_OK;
}

#endif /* SHEPPARD_USB_DFU_RUNTIME */

/* ==========================================================================
 * Class driver
 *
 * Everything that is not addressed to the DFU interface is forwarded verbatim
 * to the stock CDC driver, which keeps ownership of pClassData.
 * ========================================================================== */

static uint8_t Composite_Init(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  s_dfu_state    = DFU_STATE_APP_IDLE;
  s_detach_armed = 0U;
  return USBD_CDC.Init(pdev, cfgidx);
}

static uint8_t Composite_DeInit(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  return USBD_CDC.DeInit(pdev, cfgidx);
}

static uint8_t Composite_Setup(USBD_HandleTypeDef *pdev, USBD_SetupReqTypedef *req)
{
#if SHEPPARD_USB_DFU_RUNTIME
  if (((req->bmRequest & 0x1FU) == USB_REQ_RECIPIENT_INTERFACE) &&
      (LOBYTE(req->wIndex) == SHEPPARD_ITF_DFU))
  {
    return dfu_rt_setup(pdev, req);
  }
#endif
  return USBD_CDC.Setup(pdev, req);
}

static uint8_t Composite_EP0_TxSent(USBD_HandleTypeDef *pdev)
{
  if (USBD_CDC.EP0_TxSent != NULL)
  {
    return USBD_CDC.EP0_TxSent(pdev);
  }
  return (uint8_t)USBD_OK;
}

static uint8_t Composite_EP0_RxReady(USBD_HandleTypeDef *pdev)
{
  /* Only CDC uses the EP0 data stage (SET_LINE_CODING). The DFU run-time
     subset has no OUT data stage, so no demultiplexing is needed here. */
  if (USBD_CDC.EP0_RxReady != NULL)
  {
    return USBD_CDC.EP0_RxReady(pdev);
  }
  return (uint8_t)USBD_OK;
}

static uint8_t Composite_DataIn(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  return USBD_CDC.DataIn(pdev, epnum);
}

static uint8_t Composite_DataOut(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  return USBD_CDC.DataOut(pdev, epnum);
}

static uint8_t Composite_SOF(USBD_HandleTypeDef *pdev)
{
  if (USBD_CDC.SOF != NULL)
  {
    return USBD_CDC.SOF(pdev);
  }
  return (uint8_t)USBD_OK;
}

static uint8_t *Composite_GetHSCfgDesc(uint16_t *length)
{
  *length = (uint16_t)sizeof(s_cfg_desc_hs);
  return s_cfg_desc_hs;
}

static uint8_t *Composite_GetFSCfgDesc(uint16_t *length)
{
  *length = (uint16_t)sizeof(s_cfg_desc_fs);
  return s_cfg_desc_fs;
}

static uint8_t *Composite_GetOtherSpeedCfgDesc(uint16_t *length)
{
  /* Same layout as full speed, but reported with the OTHER_SPEED descriptor
     type. Built lazily: it is only ever requested during enumeration. */
  for (uint16_t i = 0U; i < (uint16_t)sizeof(s_cfg_desc_fs); i++)
  {
    s_cfg_desc_other[i] = s_cfg_desc_fs[i];
  }
  s_cfg_desc_other[1] = USB_DESC_TYPE_OTHER_SPEED_CONFIGURATION;

  *length = (uint16_t)sizeof(s_cfg_desc_other);
  return s_cfg_desc_other;
}

static uint8_t *Composite_GetDeviceQualifierDesc(uint16_t *length)
{
  *length = (uint16_t)sizeof(s_device_qualifier);
  return s_device_qualifier;
}

USBD_ClassTypeDef USBD_Composite = {
  .Init                          = Composite_Init,
  .DeInit                        = Composite_DeInit,
  .Setup                         = Composite_Setup,
  .EP0_TxSent                    = Composite_EP0_TxSent,
  .EP0_RxReady                   = Composite_EP0_RxReady,
  .DataIn                        = Composite_DataIn,
  .DataOut                       = Composite_DataOut,
  .SOF                           = Composite_SOF,
  .IsoINIncomplete               = NULL,
  .IsoOUTIncomplete              = NULL,
  .GetHSConfigDescriptor         = Composite_GetHSCfgDesc,
  .GetFSConfigDescriptor         = Composite_GetFSCfgDesc,
  .GetOtherSpeedConfigDescriptor = Composite_GetOtherSpeedCfgDesc,
  .GetDeviceQualifierDescriptor  = Composite_GetDeviceQualifierDesc,
};

/* ==========================================================================
 * Application interface
 * ========================================================================== */

__weak void USBD_Composite_DfuDetach(void)
{
  /* Overridden in boot_ctrl.c. */
}

void usbd_composite_task(void)
{
  if (s_detach_armed)
  {
    s_detach_armed = 0U;
    USBD_Composite_DfuDetach();
  }
}

uint8_t usbd_composite_dfu_state(void)
{
  return s_dfu_state;
}
