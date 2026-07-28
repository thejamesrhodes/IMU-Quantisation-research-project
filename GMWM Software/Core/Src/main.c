/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
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
#include "main.h"
#include "fatfs.h"
#include "usb_device.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "usbd_cdc_if.h"
#include "usbd_composite.h"
#include "sheppard_config.h"
#include "console.h"
#include "boot_ctrl.h"
#include "fwupdate.h"
#include "timebase.h"
#include "bus.h"

/* imu_icm42688.h is deliberately NOT included here.
 *
 * main.c still carries the bring-up ICM code -- its own ICM_* register
 * defines and a static icm_write8() -- which collides with the driver's
 * header on about twenty macros and one function name. That collision is a
 * symptom, not a problem to paper over: main.c should not own ICM register
 * knowledge at all, and the module split (TN-18, refactor task) deletes the
 * legacy block entirely.
 *
 * Until then main.c needs exactly one symbol from the driver, so it declares
 * that one rather than dragging in a header it conflicts with. Remove this
 * line and add the include once the legacy block is gone.
 */
void icm_console_init(void);
void validate_console_init(void);
void storage_console_init(void);
void xfer_console_init(void);
#include "led.h"
void sampler_on_int(uint16_t gpio_pin);   /* sampler.h; declared to avoid
                                             pulling in bus.h/record.h here */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
typedef struct {
  SPI_HandleTypeDef *hspi;
  GPIO_TypeDef      *cs_port;   uint16_t cs_pin;
  GPIO_TypeDef      *led_port;  uint16_t led_pin;
  uint16_t           int_pin;                 /* data-ready EXTI pin */
} bus_t;
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define LED_ON   GPIO_PIN_SET      /* swap these two if LEDs are active-low */
#define LED_OFF  GPIO_PIN_RESET
#define SPI_TMO  100U              /* ms/transfer; timeout guards a dead bus */
#define DUMP_REGS        16U       /* how many regs to hex-dump on a dead bus   */
#define RATE_WINDOW_MS   10000U    /* default `rate` measurement window         */



#define ICM_TEMP_DATA1   0x1D
#define ICM_ACCEL_DATA_X1 0x1F   /* 6 bytes: X1 X0 Y1 Y0 Z1 Z0 */
#define ICM_GYRO_DATA_X1  0x25   /* 6 bytes: X1 X0 Y1 Y0 Z1 Z0 */
#define ICM_PWR_MGMT0     0x4E


#define ICM_GYRO_CONFIG0   0x4F
#define ICM_ACCEL_CONFIG0  0x50

/* ---- ICM-42688-P ----  FS_SEL=000 (±2000 dps / ±16 g) | ODR 0x8 = 100 Hz */
#define ICM_FS_MAX_ODR_100HZ  ((0x0U << 5) | 0x08U)   /* was 0x0A = 25 Hz */

#define ERR_HERE()  do { g_err_file = __FILE__; g_err_line = __LINE__; Error_Handler(); } while (0)

/* ---- ISM330DHCX ---- */
#define ISM_CTRL1_XL      0x10
#define ISM_CTRL2_G       0x11
#define ISM_CTRL3_C       0x12
#define ISM_OUT_TEMP_L    0x20   /* burst 14 B: temp(2) gyro(6) accel(6) */
/* ODR 104 Hz (0010<<4) | FS_XL 01 (±16 g) <<2 */
#define ISM_CTRL1_XL_VAL  0x44
/* ODR 104 Hz (0010<<4) | FS_G 11 (±2000 dps) <<2 | FS_125=0 | FS_4000=0 */
#define ISM_CTRL2_G_VAL   0x4C
/* BDU=1 (bit6) prevents torn LSB/MSB across samples; IF_INC=1 (bit2) for bursts */
#define ISM_CTRL3_C_VAL   0x44

/* ---- BMI323 ---- */
#define BMI_ACC_CONF      0x20
#define BMI_GYR_CONF      0x21
#define BMI_ACC_X         0x03   /* burst 7 words: accel(3) gyro(3) temp(1) */
/* mode 7 (high-perf) <<12 | range <<4 | ODR 100 Hz (0x6) */
#define BMI_ACC_CONF_VAL  0x7038 /* ±16 g  */
#define BMI_GYR_CONF_VAL  0x7048 /* ±2000 dps */

#define ICM_REG_BANK_SEL          0x76
#define ICM_GYRO_CONFIG1          0x51   /* [3:2] GYRO_UI_FILT_ORD          */
#define ICM_GYRO_ACCEL_CONFIG0    0x52   /* [7:4] ACCEL bw, [3:0] GYRO bw   */
#define ICM_ACCEL_CONFIG1         0x53   /* [4:3] ACCEL_UI_FILT_ORD         */
/* bank 1 */
#define ICM_GYRO_CFG_STATIC3      0x0C
#define ICM_GYRO_CFG_STATIC4      0x0D
#define ICM_GYRO_CFG_STATIC5      0x0E
/* bank 2 */
#define ICM_ACCEL_CFG_STATIC2     0x03   /* [6:1] ACCEL_AAF_DELT, [0] AAF_DIS */
#define ICM_ACCEL_CFG_STATIC3     0x04
#define ICM_ACCEL_CFG_STATIC4     0x05

/* UI filter bandwidth code: 0 = ODR/2 (matches BMI323 bw bit = 0 and the
   ISM330DHCX default chain). Both nibbles of 0x52 set to 0.               */
#define ICM_UI_BW_ODR_OVER_2      0x00

/* AAF ~42 Hz, the lowest cutoff the part supports.
   [VERIFY] these three numbers against the AAF table in DS-000347 §5.3
   before any data you intend to keep — I have not confirmed them from the
   datasheet table in this session, only the register addresses above.     */
#define ICM_AAF_DELT              1
#define ICM_AAF_DELTSQR           1
#define ICM_AAF_BITSHIFT          15


#define RTC_MAGIC  0x5348u   /* 'SH' — marks the RTC as already set */

/* ---- data-ready interrupt registers ----
   [verify] bit-field values below are from driver convention, not the
   datasheets. Step 2.9 validates them empirically. */
#define ICM_INT_CONFIG    0x14
#define ICM_INT_CONFIG1   0x64
#define ICM_INT_SOURCE0   0x65
#define ICM_INT_STATUS    0x2D

#define ISM_INT1_CTRL     0x0D
#define ISM_STATUS_REG    0x1E

#define BMI_IO_INT_CTRL   0x38
#define BMI_INT_MAP2      0x3B
#define BMI_INT_STATUS1   0x0D

/* [verify] COUNTER_BDR_REG1 addr/bit against the ISM330DHCX datasheet */
#define ISM_COUNTER_BDR_REG1  0x0B
#define ISM_DRDY_PULSED       0x80   /* bit 7 */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;

I2C_HandleTypeDef hi2c1;

RTC_HandleTypeDef hrtc;

SD_HandleTypeDef hsd2;

SPI_HandleTypeDef hspi1;
SPI_HandleTypeDef hspi3;
SPI_HandleTypeDef hspi4;
SPI_HandleTypeDef hspi5;
DMA_HandleTypeDef hdma_spi1_rx;
DMA_HandleTypeDef hdma_spi1_tx;
DMA_HandleTypeDef hdma_spi3_rx;
DMA_HandleTypeDef hdma_spi3_tx;

TIM_HandleTypeDef htim2;

UART_HandleTypeDef huart4;
UART_HandleTypeDef huart1;

/* USER CODE BEGIN PV */
static const bus_t g_buses[4] = {
  { &hspi1, CS_1_GPIO_Port, CS_1_Pin, LED_1_GPIO_Port, LED_1_Pin, INT1_1_Pin },  /* slot 1 ICM */
  { &hspi3, CS_2_GPIO_Port, CS_2_Pin, LED_2_GPIO_Port, LED_2_Pin, INT2_1_Pin },  /* slot 2 ICM */
  { &hspi5, CS_3_GPIO_Port, CS_3_Pin, LED_3_GPIO_Port, LED_3_Pin, INT3_1_Pin },  /* slot 3 ISM */
  { &hspi4, CS_4_GPIO_Port, CS_4_Pin, LED_4_GPIO_Port, LED_4_Pin, INT4_1_Pin },  /* slot 4 BMI */
};

static volatile uint32_t g_drdy_count[4] = {0};
static volatile uint32_t g_drdy_flag     = 0;   /* bit i set = bus i has new data */

static const char *g_err_file = "unknown";
static int         g_err_line = 0;

extern USBD_HandleTypeDef hUsbDeviceHS;   /* defined in usb_device.c */

/* Console commands owned by main.c. Handlers are defined in USER CODE 4.
   The prototypes must be HERE and not in USER CODE PFP: PV is emitted before
   PFP, so the table below would otherwise reference undeclared identifiers.
   Modules added later register their own tables rather than extending this. */
static void cmd_scan(int argc, char **argv);
static void cmd_sd(int argc, char **argv);
static void cmd_burst(int argc, char **argv);
static void cmd_time(int argc, char **argv);
static void cmd_rate(int argc, char **argv);
static void cmd_tick(int argc, char **argv);

/* Non-blocking data-ready rate measurement. Started by `rate`, completed by
   rate_task() in the main loop. */
static uint32_t g_rate_c0[4]  = {0};
static uint32_t g_rate_t0     = 0;
static uint32_t g_rate_window = 0;
static uint8_t  g_rate_active = 0;

static const console_cmd_t g_main_cmds[] = {
  { "scan",  "identify all four buses and dump one sample", cmd_scan  },
  { "tick",  "tick [s] - check the 1 us timebase against SysTick", cmd_tick },
  { "rate",  "rate [s|stop] - measure true ODR, runs in the background", cmd_rate },
  { "sd",    "mount the card and run the FS self-test", cmd_sd    },
  { "burst", "burst <n> - CDC throughput test, n x 512 B", cmd_burst },
  { "time",  "time YYYY-MM-DD HH:MM:SS - set the RTC", cmd_time  },
};
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MPU_Config(void);
static void MX_GPIO_Init(void);
static void MX_DMA_Init(void);
static void MX_SPI1_Init(void);
static void MX_SPI3_Init(void);
static void MX_SPI4_Init(void);
static void MX_SPI5_Init(void);
static void MX_UART4_Init(void);
static void MX_ADC1_Init(void);
static void MX_I2C1_Init(void);
static void MX_SDMMC2_SD_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_RTC_Init(void);
static void MX_TIM2_Init(void);
/* USER CODE BEGIN PFP */



static uint8_t spi_read8(const bus_t *b, uint8_t reg);
static uint8_t bmi323_chipid(const bus_t *b);
static int     bus_present(const bus_t *b);
static void uart_log(const char *fmt, ...);
static void print_banner(void);
static void scan_all_buses(void);
static void hexdump_bus(const bus_t *b, uint8_t start_reg, uint8_t count);




static void icm_write8(const bus_t *b, uint8_t reg, uint8_t val);
static void icm_burst_read(const bus_t *b, uint8_t reg, uint8_t *dst, uint8_t n);
static void icm_mvp_log(const bus_t *b, int idx);


static void error_dump(void);





static void fs_test(void);


static void ism_configure(const bus_t *b);
static void ism_mvp_log(const bus_t *b, int idx);
static void bmi_write16(const bus_t *b, uint8_t reg, uint16_t val);
static uint16_t bmi_read16(const bus_t *b, uint8_t reg);
static void bmi_burst16(const bus_t *b, uint8_t reg, uint16_t *dst, uint8_t nwords);
static void bmi_configure(const bus_t *b);
static void bmi_mvp_log(const bus_t *b, int idx);
static void sensor_configure(const bus_t *b);
static void sensor_mvp_log(const bus_t *b, int idx);

static void icm_bank(const bus_t *b, uint8_t bank);
static void icm_rmw(const bus_t *b, uint8_t reg, uint8_t mask, uint8_t val);
static void icm_configure_matched(const bus_t *b);


static int  cdc_write(const uint8_t *buf, uint16_t len);
static void cdc_burst(uint32_t nchunks);

static void rtc_init_once(void);
static void rtc_print(void);


static void icm_enable_drdy(const bus_t *b);
static void ism_enable_drdy(const bus_t *b);
static void bmi_enable_drdy(const bus_t *b);

/* Console command handlers are prototyped in USER CODE PV, immediately above
   the table that references them -- see the note there. */
static void rate_task(void);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
#if SHEPPARD_VTOR_RELOCATE
  /* Point the vector table at wherever this image was linked. A no-op while
     SHEPPARD_APP_BASE is 0x08000000; load-bearing the moment the DFU loader
     occupies the low sectors and the application moves to 0x08010000.
     Must happen before HAL_Init() enables SysTick, or the first tick vectors
     into the loader's table. */
  SCB->VTOR = SHEPPARD_APP_BASE;
  __DSB();
#endif
  /* USER CODE END 1 */

  /* MPU Configuration--------------------------------------------------------*/
  MPU_Config();

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_SPI1_Init();
  MX_SPI3_Init();
  MX_SPI4_Init();
  MX_SPI5_Init();
  MX_USB_DEVICE_Init();
  MX_UART4_Init();
  MX_ADC1_Init();
  MX_I2C1_Init();
  MX_SDMMC2_SD_Init();
  MX_USART1_UART_Init();
  MX_RTC_Init();
  MX_FATFS_Init();
  MX_TIM2_Init();
  /* USER CODE BEGIN 2 */

  /* Console first: everything below logs through it. Output goes to CDC when
     enumerated and to USART1 while SHEPPARD_CONSOLE_UART_MIRROR is set. */
  console_init();
  console_register(g_main_cmds, (uint8_t)(sizeof g_main_cmds / sizeof g_main_cmds[0]));

  /* Reads the boot state the loader left in the backup registers and starts
     the healthy-boot timer. Requires MX_RTC_Init() to have run. */
  boot_ctrl_init();

  /* Registers the `fw` command. Must follow console_init(). */
  fw_init();

  /* 1 us timebase. Must follow MX_TIM2_Init(). Every sample timestamp and
     every f_measured figure comes from here. */
  if (timebase_init() != 0) {
    console_printf("timebase: TIM2 failed to start\r\n");
  }

  /* SPI transport. Must follow the MX_SPIx_Init() calls and MX_DMA_Init().
     Deasserts every chip select, which the legacy code below also does --
     harmless duplication until the old helpers are retired. */
  bus_init();

  /* Registers the `icm` and `fifo` commands, and `m1`. */
  icm_console_init();
  validate_console_init();
  storage_console_init();

  /* Registers `ls`, `get` and `rm`. The board has no removable card reader, so
     this is the only route from the instrument to analysis. */
  xfer_console_init();

  /* Status indication for unattended runs. Must follow MX_GPIO_Init() and
     timebase_init(). */
  led_init();

  HAL_Delay(500);
  HAL_GPIO_WritePin(LED_1_GPIO_Port, LED_1_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(LED_2_GPIO_Port, LED_2_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(LED_3_GPIO_Port, LED_3_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(LED_4_GPIO_Port, LED_4_Pin, GPIO_PIN_RESET);
  HAL_Delay(500);



  HAL_Delay(50);                               /* let sensors finish power-on reset */
  for (int i = 0; i < 4; i++)
    HAL_GPIO_WritePin(g_buses[i].cs_port, g_buses[i].cs_pin, GPIO_PIN_SET);

  /* Give the host a bounded chance to enumerate and open the port before the
     boot report goes out. Data sent before the port is opened is discarded
     (TN-16 SS7.2), and this is the one report that is not repeatable on
     demand -- everything in it except fs_test() is, via `scan` and `sd`.
     Falls through immediately when nothing is attached. */
  for (uint32_t t0 = HAL_GetTick();
       !console_cdc_ready() && (HAL_GetTick() - t0) < 2500U; )
  {
    HAL_Delay(10);
  }

  /* ---- boot self-test: runs once, then never again ---------------------- */
  print_banner();
  scan_all_buses();                                 /* identify all four     */
  for (int i = 0; i < 4; i++) sensor_configure(&g_buses[i]);
  for (int i = 0; i < 4; i++) sensor_mvp_log(&g_buses[i], i);   /* one sample */

  rtc_init_once();
  rtc_print();

  fs_test();

  console_printf("boot self-test done. `help` for commands.\r\n");
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {

    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */

      /* The loop does housekeeping and nothing else. Everything that used to
         print on a timer -- bus rescan, sample dump, USB state, data-ready
         rate -- is now on demand via `scan`, `usb` and `rate`. Unsolicited
         console traffic corrupts a firmware transfer, makes captured logs
         unparseable, and puts SPI activity on the bus at moments nobody
         asked for, which is not what you want on a noise measurement. */
      console_task();          /* assemble input lines, dispatch commands    */
      fw_task();               /* image verify / erase / reprogram / reset   */
      rate_task();             /* finish an armed data-ready measurement     */
      usbd_composite_task();   /* deliver a pending DFU_DETACH out of the ISR */
      boot_ctrl_task();        /* healthy-boot latch, and the deferred reset  */
      led_task();              /* status indication, non-blocking            */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE3);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE|RCC_OSCILLATORTYPE_LSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_BYPASS;
  RCC_OscInitStruct.LSEState = RCC_LSE_BYPASS;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 12;
  RCC_OscInitStruct.PLL.PLLN = 96;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV6;
  RCC_OscInitStruct.PLL.PLLQ = 4;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_1) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief ADC1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_ADC1_Init(void)
{

  /* USER CODE BEGIN ADC1_Init 0 */

  /* USER CODE END ADC1_Init 0 */

  ADC_ChannelConfTypeDef sConfig = {0};

  /* USER CODE BEGIN ADC1_Init 1 */

  /* USER CODE END ADC1_Init 1 */

  /** Configure the global features of the ADC (Clock, Resolution, Data Alignment and number of conversion)
  */
  hadc1.Instance = ADC1;
  hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV2;
  hadc1.Init.Resolution = ADC_RESOLUTION_12B;
  hadc1.Init.ScanConvMode = ADC_SCAN_DISABLE;
  hadc1.Init.ContinuousConvMode = DISABLE;
  hadc1.Init.DiscontinuousConvMode = DISABLE;
  hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_NONE;
  hadc1.Init.ExternalTrigConv = ADC_SOFTWARE_START;
  hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc1.Init.NbrOfConversion = 1;
  hadc1.Init.DMAContinuousRequests = DISABLE;
  hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
  if (HAL_ADC_Init(&hadc1) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure for the selected ADC regular channel its corresponding rank in the sequencer and its sample time.
  */
  sConfig.Channel = ADC_CHANNEL_10;
  sConfig.Rank = ADC_REGULAR_RANK_1;
  sConfig.SamplingTime = ADC_SAMPLETIME_480CYCLES;
  if (HAL_ADC_ConfigChannel(&hadc1, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN ADC1_Init 2 */

  /* USER CODE END ADC1_Init 2 */

}

/**
  * @brief I2C1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_I2C1_Init(void)
{

  /* USER CODE BEGIN I2C1_Init 0 */

  /* USER CODE END I2C1_Init 0 */

  /* USER CODE BEGIN I2C1_Init 1 */

  /* USER CODE END I2C1_Init 1 */
  hi2c1.Instance = I2C1;
  hi2c1.Init.Timing = 0x00707CBB;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0;
  hi2c1.Init.OwnAddress2Masks = I2C_OA2_NOMASK;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Analogue filter
  */
  if (HAL_I2CEx_ConfigAnalogFilter(&hi2c1, I2C_ANALOGFILTER_ENABLE) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Digital filter
  */
  if (HAL_I2CEx_ConfigDigitalFilter(&hi2c1, 0) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN I2C1_Init 2 */

  /* USER CODE END I2C1_Init 2 */

}

/**
  * @brief RTC Initialization Function
  * @param None
  * @retval None
  */
static void MX_RTC_Init(void)
{

  /* USER CODE BEGIN RTC_Init 0 */

  /* USER CODE END RTC_Init 0 */

  /* USER CODE BEGIN RTC_Init 1 */

  /* USER CODE END RTC_Init 1 */

  /** Initialize RTC Only
  */
  hrtc.Instance = RTC;
  hrtc.Init.HourFormat = RTC_HOURFORMAT_24;
  hrtc.Init.AsynchPrediv = 127;
  hrtc.Init.SynchPrediv = 255;
  hrtc.Init.OutPut = RTC_OUTPUT_DISABLE;
  hrtc.Init.OutPutPolarity = RTC_OUTPUT_POLARITY_HIGH;
  hrtc.Init.OutPutType = RTC_OUTPUT_TYPE_OPENDRAIN;
  if (HAL_RTC_Init(&hrtc) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN RTC_Init 2 */

  /* USER CODE END RTC_Init 2 */

}

/**
  * @brief SDMMC2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SDMMC2_SD_Init(void)
{

  /* USER CODE BEGIN SDMMC2_Init 0 */

  /* USER CODE END SDMMC2_Init 0 */

  /* USER CODE BEGIN SDMMC2_Init 1 */

  /* USER CODE END SDMMC2_Init 1 */
  hsd2.Instance = SDMMC2;
  hsd2.Init.ClockEdge = SDMMC_CLOCK_EDGE_RISING;
  hsd2.Init.ClockBypass = SDMMC_CLOCK_BYPASS_DISABLE;
  hsd2.Init.ClockPowerSave = SDMMC_CLOCK_POWER_SAVE_ENABLE;
  hsd2.Init.BusWide = SDMMC_BUS_WIDE_1B;
  hsd2.Init.HardwareFlowControl = SDMMC_HARDWARE_FLOW_CONTROL_ENABLE;
  hsd2.Init.ClockDiv = 0;
  /* USER CODE BEGIN SDMMC2_Init 2 */

  /* USER CODE END SDMMC2_Init 2 */

}

/**
  * @brief SPI1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI1_Init(void)
{

  /* USER CODE BEGIN SPI1_Init 0 */

  /* USER CODE END SPI1_Init 0 */

  /* USER CODE BEGIN SPI1_Init 1 */

  /* USER CODE END SPI1_Init 1 */
  /* SPI1 parameter configuration*/
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi1.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi1.Init.NSS = SPI_NSS_SOFT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_4;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 7;
  hspi1.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi1.Init.NSSPMode = SPI_NSS_PULSE_ENABLE;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI1_Init 2 */

  /* USER CODE END SPI1_Init 2 */

}

/**
  * @brief SPI3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI3_Init(void)
{

  /* USER CODE BEGIN SPI3_Init 0 */

  /* USER CODE END SPI3_Init 0 */

  /* USER CODE BEGIN SPI3_Init 1 */

  /* USER CODE END SPI3_Init 1 */
  /* SPI3 parameter configuration*/
  hspi3.Instance = SPI3;
  hspi3.Init.Mode = SPI_MODE_MASTER;
  hspi3.Init.Direction = SPI_DIRECTION_2LINES;
  hspi3.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi3.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi3.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi3.Init.NSS = SPI_NSS_SOFT;
  hspi3.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_2;
  hspi3.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi3.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi3.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi3.Init.CRCPolynomial = 7;
  hspi3.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi3.Init.NSSPMode = SPI_NSS_PULSE_ENABLE;
  if (HAL_SPI_Init(&hspi3) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI3_Init 2 */

  /* USER CODE END SPI3_Init 2 */

}

/**
  * @brief SPI4 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI4_Init(void)
{

  /* USER CODE BEGIN SPI4_Init 0 */

  /* USER CODE END SPI4_Init 0 */

  /* USER CODE BEGIN SPI4_Init 1 */

  /* USER CODE END SPI4_Init 1 */
  /* SPI4 parameter configuration*/
  hspi4.Instance = SPI4;
  hspi4.Init.Mode = SPI_MODE_MASTER;
  hspi4.Init.Direction = SPI_DIRECTION_2LINES;
  hspi4.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi4.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi4.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi4.Init.NSS = SPI_NSS_SOFT;
  hspi4.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_4;
  hspi4.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi4.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi4.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi4.Init.CRCPolynomial = 7;
  hspi4.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi4.Init.NSSPMode = SPI_NSS_PULSE_ENABLE;
  if (HAL_SPI_Init(&hspi4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI4_Init 2 */

  /* USER CODE END SPI4_Init 2 */

}

/**
  * @brief SPI5 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI5_Init(void)
{

  /* USER CODE BEGIN SPI5_Init 0 */

  /* USER CODE END SPI5_Init 0 */

  /* USER CODE BEGIN SPI5_Init 1 */

  /* USER CODE END SPI5_Init 1 */
  /* SPI5 parameter configuration*/
  hspi5.Instance = SPI5;
  hspi5.Init.Mode = SPI_MODE_MASTER;
  hspi5.Init.Direction = SPI_DIRECTION_2LINES;
  hspi5.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi5.Init.CLKPolarity = SPI_POLARITY_HIGH;
  hspi5.Init.CLKPhase = SPI_PHASE_2EDGE;
  hspi5.Init.NSS = SPI_NSS_SOFT;
  hspi5.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_4;
  hspi5.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi5.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi5.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi5.Init.CRCPolynomial = 7;
  hspi5.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi5.Init.NSSPMode = SPI_NSS_PULSE_DISABLE;
  if (HAL_SPI_Init(&hspi5) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI5_Init 2 */

  /* USER CODE END SPI5_Init 2 */

}

/**
  * @brief TIM2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM2_Init(void)
{

  /* USER CODE BEGIN TIM2_Init 0 */

  /* USER CODE END TIM2_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 31;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 4294967295;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim2, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */

}

/**
  * @brief UART4 Initialization Function
  * @param None
  * @retval None
  */
static void MX_UART4_Init(void)
{

  /* USER CODE BEGIN UART4_Init 0 */

  /* USER CODE END UART4_Init 0 */

  /* USER CODE BEGIN UART4_Init 1 */

  /* USER CODE END UART4_Init 1 */
  huart4.Instance = UART4;
  huart4.Init.BaudRate = 115200;
  huart4.Init.WordLength = UART_WORDLENGTH_8B;
  huart4.Init.StopBits = UART_STOPBITS_1;
  huart4.Init.Parity = UART_PARITY_NONE;
  huart4.Init.Mode = UART_MODE_TX_RX;
  huart4.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart4.Init.OverSampling = UART_OVERSAMPLING_16;
  huart4.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart4.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN UART4_Init 2 */

  /* USER CODE END UART4_Init 2 */

}

/**
  * @brief USART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

/**
  * Enable DMA controller clock
  */
static void MX_DMA_Init(void)
{

  /* DMA controller clock enable */
  __HAL_RCC_DMA2_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();

  /* DMA interrupt init */
  /* DMA1_Stream0_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Stream0_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream0_IRQn);
  /* DMA1_Stream5_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Stream5_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream5_IRQn);
  /* DMA2_Stream2_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA2_Stream2_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream2_IRQn);
  /* DMA2_Stream3_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA2_Stream3_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream3_IRQn);

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOG_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(CS_3_GPIO_Port, CS_3_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(CS_1_GPIO_Port, CS_1_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(CS_4_GPIO_Port, CS_4_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOE, LED_1_Pin|LED_2_Pin|LED_3_Pin|LED_4_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(CS_2_GPIO_Port, CS_2_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin : INT4_1_Pin */
  GPIO_InitStruct.Pin = INT4_1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(INT4_1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : INT3_1_Pin */
  GPIO_InitStruct.Pin = INT3_1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(INT3_1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : CS_3_Pin */
  GPIO_InitStruct.Pin = CS_3_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(CS_3_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : CS_1_Pin */
  GPIO_InitStruct.Pin = CS_1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(CS_1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : CS_4_Pin LED_1_Pin LED_2_Pin LED_3_Pin
                           LED_4_Pin */
  GPIO_InitStruct.Pin = CS_4_Pin|LED_1_Pin|LED_2_Pin|LED_3_Pin
                          |LED_4_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  /*Configure GPIO pin : INT1_1_Pin */
  GPIO_InitStruct.Pin = INT1_1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(INT1_1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : INT2_1_Pin */
  GPIO_InitStruct.Pin = INT2_1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(INT2_1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : CS_2_Pin */
  GPIO_InitStruct.Pin = CS_2_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(CS_2_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : CD_Pin */
  GPIO_InitStruct.Pin = CD_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(CD_GPIO_Port, &GPIO_InitStruct);

  /* EXTI interrupt init*/
  HAL_NVIC_SetPriority(EXTI3_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI3_IRQn);

  HAL_NVIC_SetPriority(EXTI9_5_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI9_5_IRQn);

  HAL_NVIC_SetPriority(EXTI15_10_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */



/* ST / InvenSense style: addr|0x80 = read, one dummy byte clocks out the data */
static uint8_t spi_read8(const bus_t *b, uint8_t reg)
{
  uint8_t tx[2] = { (uint8_t)(reg | 0x80U), 0x00U };
  uint8_t rx[2] = { 0 };
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_RESET);
  HAL_SPI_TransmitReceive(b->hspi, tx, rx, 2, SPI_TMO);
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_SET);
  return rx[1];
}

/* BMI323: 16-bit regs; on SPI a read returns 1 dummy byte, then LSB, MSB */
static uint8_t bmi323_chipid(const bus_t *b)
{
  uint8_t tx[4] = { (uint8_t)(0x00U | 0x80U), 0, 0, 0 };  /* CHIP_ID @ 0x00 */
  uint8_t rx[4] = { 0 };
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_RESET);
  HAL_SPI_TransmitReceive(b->hspi, tx, rx, 4, SPI_TMO);
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_SET);
  return rx[2];                              /* rx[1]=dummy, rx[2]=id LSB, rx[3]=MSB */
}

/* Try every IMU your board may carry; 1 if any valid WHO_AM_I answers.
   Order matters: ICM/ISM are checked first so the BMI323 path only runs
   on a bus that is neither, avoiding cross-talk false positives.        */
static int bus_present(const bus_t *b)
{
  if (spi_read8(b, 0x75) == 0x47) return 1;  /* ICM-42688-P */
  if (spi_read8(b, 0x0F) == 0x6B) return 1;  /* ISM330DHCX  */
  (void)bmi323_chipid(b);                    /* 1st read latches BMI323 into SPI */
  if (bmi323_chipid(b) == 0x43) return 1;    /* BMI323 */
  return 0;
}




/* Kept as a thin shim so the ~60 existing call sites did not all have to
   change in one edit. New code should call console_printf() directly; this
   name will go away during the module split.

   Output now reaches CDC and, while SHEPPARD_CONSOLE_UART_MIRROR is set,
   USART1 as well. Safe to call before console_init(): console_write() checks
   both sinks itself. Still blocking, still not for a hot data path, still
   never from an ISR. */
static void uart_log(const char *fmt, ...)
{
  va_list ap;
  va_start(ap, fmt);
  console_vprintf(fmt, ap);
  va_end(ap);
}

static void print_banner(void)
{
  uart_log("\r\n==================== Sheppard bring-up ====================\r\n");
  uart_log("Build: %s %s\r\n", __DATE__, __TIME__);
  uart_log("SYSCLK=%lu Hz  HCLK=%lu Hz  PCLK1=%lu Hz  PCLK2=%lu Hz\r\n",
            (unsigned long)HAL_RCC_GetSysClockFreq(),
            (unsigned long)HAL_RCC_GetHCLKFreq(),
            (unsigned long)HAL_RCC_GetPCLK1Freq(),
            (unsigned long)HAL_RCC_GetPCLK2Freq());
  uart_log("=============================================================\r\n");
}

/* Raw register dump — no interpretation, just bytes. Only called on a bus
   that failed every known WHO_AM_I match, to see if it's truly dead
   (constant 0x00 / 0xFF) or answering something unexpected (a real but
   unrecognised chip, an address-offset bug, or a noisy/floating line). */
static void hexdump_bus(const bus_t *b, uint8_t start_reg, uint8_t count)
{
  char line[96];
  int pos = snprintf(line, sizeof line, "    regs 0x%02X..0x%02X:",
                      start_reg, (uint8_t)(start_reg + count - 1));
  for (uint8_t i = 0; i < count; i++) {
    if (pos >= (int)sizeof line - 4) break;          /* clamp */
    uint8_t v = spi_read8(b, (uint8_t)(start_reg + i));
    pos += snprintf(line + pos, sizeof(line) - (size_t)pos, " %02X", v);
  }
  pos += snprintf(line + pos, sizeof(line) - pos, "\r\n");
  HAL_UART_Transmit(&huart1, (uint8_t*)line, pos, 100);
}

static void scan_all_buses(void)
{
	static const char *names[4] = { "bus1(SPI1/ICM)", "bus2(SPI3/ICM)",
	                                "bus3(SPI5/ISM)", "bus4(SPI4/BMI)" };
  uint32_t t = HAL_GetTick();

  uart_log("--- scan @ t=%lu ms ---\r\n", (unsigned long)t);

  for (int i = 0; i < 4; i++) {
    const bus_t *b = &g_buses[i];
    uint8_t icm = spi_read8(b, 0x75);
    uint8_t ism = spi_read8(b, 0x0F);
    uint8_t bmi = bmi323_chipid(b);
    int present = bus_present(b);

    const char *ident = "NONE";
    if (icm == 0x47)      ident = "ICM-42688-P";
    else if (ism == 0x6B) ident = "ISM330DHCX";
    else if (bmi == 0x43) ident = "BMI323";

    uart_log("%-11s ICM=0x%02X ISM=0x%02X BMI=0x%02X  -> %s%s\r\n",
              names[i], icm, ism, bmi, ident,
              present ? "" : "  [DEAD/UNKNOWN]");

    HAL_GPIO_WritePin(b->led_port, b->led_pin, present ? LED_ON : LED_OFF);

    if (!present) hexdump_bus(b, 0x00, DUMP_REGS);   /* extra detail only when needed */
  }
}





static void icm_write8(const bus_t *b, uint8_t reg, uint8_t val)
{
  uint8_t tx[2] = { (uint8_t)(reg & 0x7FU), val };   /* bit7=0 -> write */
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_RESET);
  HAL_SPI_Transmit(b->hspi, tx, 2, SPI_TMO);
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_SET);
}

/* One CS assertion for the whole burst -- proves multi-byte reads work,
   not just single-register WHO_AM_I. */
static void icm_burst_read(const bus_t *b, uint8_t reg, uint8_t *dst, uint8_t n)
{
  uint8_t tx[1 + 14] = {0};
  uint8_t rx[1 + 14] = {0};
  tx[0] = (uint8_t)(reg | 0x80U);
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_RESET);
  HAL_SPI_TransmitReceive(b->hspi, tx, rx, (uint16_t)(n + 1), SPI_TMO);
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_SET);
  for (uint8_t i = 0; i < n; i++) dst[i] = rx[i + 1];
}

static void icm_mvp_log(const bus_t *b, int idx)
{

  uint8_t g_cfg = spi_read8(b, ICM_GYRO_CONFIG0);
  uint8_t a_cfg = spi_read8(b, ICM_ACCEL_CONFIG0);
  uart_log("bus%d cfg: GYRO_CONFIG0=0x%02X ACCEL_CONFIG0=0x%02X\r\n",
            idx + 1, g_cfg, a_cfg);

  uint8_t temp[2], accel[6], gyro[6];
  icm_burst_read(b, ICM_TEMP_DATA1, temp, 2);
  icm_burst_read(b, ICM_ACCEL_DATA_X1, accel, 6);
  icm_burst_read(b, ICM_GYRO_DATA_X1, gyro, 6);

  int16_t traw = (int16_t)((temp[0]  << 8) | temp[1]);
  int16_t ax   = (int16_t)((accel[0] << 8) | accel[1]);
  int16_t ay   = (int16_t)((accel[2] << 8) | accel[3]);
  int16_t az   = (int16_t)((accel[4] << 8) | accel[5]);
  int16_t gx   = (int16_t)((gyro[0]  << 8) | gyro[1]);
  int16_t gy   = (int16_t)((gyro[2]  << 8) | gyro[3]);
  int16_t gz   = (int16_t)((gyro[4]  << 8) | gyro[5]);

  uart_log("bus%d ICM raw: T=%d  A=[%d %d %d]  G=[%d %d %d]\r\n",
            idx + 1, traw, ax, ay, az, gx, gy, gz);

  icm_bank(b, 1);
    uint8_t d3 = spi_read8(b, ICM_GYRO_CFG_STATIC3);
    uint8_t d5 = spi_read8(b, ICM_GYRO_CFG_STATIC5);
    icm_bank(b, 0);
    uart_log("bus%d filt: UI_BW=0x%02X GYRO_AAF_DELT=%u BITSHIFT=%u\r\n",
              idx + 1, spi_read8(b, ICM_GYRO_ACCEL_CONFIG0),
              (unsigned)(d3 & 0x3FU), (unsigned)(d5 >> 4));
}




/* Dumps every peripheral's HAL error code so you don't have to guess which
   MX_*_Init() call actually failed. Only meaningful for handles whose
   Init() ran before this one failed -- later ones are still zeroed. */
static void error_dump(void)
{
  uart_log("\r\n!!!!!!!!!!!!!!!! Error_Handler() !!!!!!!!!!!!!!!!\r\n");
  uart_log("at %s:%d  tick=%lu\r\n", g_err_file, g_err_line,
            (unsigned long)HAL_GetTick());
  uart_log("hspi1  Err=0x%08lX State=%d\r\n", (unsigned long)hspi1.ErrorCode, (int)hspi1.State);
  uart_log("hspi3  Err=0x%08lX State=%d\r\n", (unsigned long)hspi3.ErrorCode, (int)hspi3.State);
  uart_log("hspi4  Err=0x%08lX State=%d\r\n", (unsigned long)hspi4.ErrorCode, (int)hspi4.State);
  uart_log("hspi5  Err=0x%08lX State=%d\r\n", (unsigned long)hspi5.ErrorCode, (int)hspi5.State);
  uart_log("huart1 Err=0x%08lX gState=%d RxState=%d\r\n",
            (unsigned long)huart1.ErrorCode, (int)huart1.gState, (int)huart1.RxState);
  uart_log("huart4 Err=0x%08lX gState=%d RxState=%d\r\n",
            (unsigned long)huart4.ErrorCode, (int)huart4.gState, (int)huart4.RxState);
  uart_log("hi2c1  Err=0x%08lX State=%d\r\n", (unsigned long)hi2c1.ErrorCode, (int)hi2c1.State);
  uart_log("hadc1  Err=0x%08lX State=%d\r\n", (unsigned long)hadc1.ErrorCode, (int)hadc1.State);
  uart_log("hrtc   State=%d  (no ErrorCode field on F7)\r\n", (int)hrtc.State);
  uart_log("hsd2   Err=0x%08lX State=%d\r\n", (unsigned long)hsd2.ErrorCode, (int)hsd2.State);
  uart_log("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\r\n");
}


static FATFS   g_fs;
static FIL     g_fil;
static uint8_t g_blk[4096];        /* throughput chunk — static, not stack */

static void fs_test(void)
{
	uart_log("fs_test: SDPath=\"%s\" retSD=%d\r\n", SDPath, (int)retSD);
  FRESULT fr;
  UINT    bw, br;
  char    rd[96] = {0};

  /* --- mount (opt=1 forces immediate mount so errors surface here) --- */
  uint8_t bsp = BSP_SD_Init();
    uart_log("BSP_SD_Init -> %d (0=OK 1=ERROR 2=BUSY 3=TIMEOUT 4=NOT_PRESENT)\r\n", bsp);
    uart_log("  hsd2.Instance=%p ErrorCode=0x%08lX State=%d\r\n",
              (void*)hsd2.Instance, (unsigned long)hsd2.ErrorCode, (int)hsd2.State);
  fr = f_mount(&g_fs, SDPath, 1);
  uart_log("f_mount(\"%s\") -> %d\r\n", SDPath, fr);
  if (fr != FR_OK) {
    uart_log("  1=DISK_ERR 3=NOT_READY 13=NO_FILESYSTEM 19=INVALID_DRIVE\r\n");
    if (fr == FR_NO_FILESYSTEM)
      uart_log("  -> exFAT not enabled in ffconf.h, or volume is unformatted\r\n");
    return;
  }

  uart_log("fs_type=%d (1=FAT12 2=FAT16 3=FAT32 4=exFAT)  csize=%u sect\r\n",
            (int)g_fs.fs_type, (unsigned)g_fs.csize);

  DWORD fre_clust; FATFS *fsp;
  if (f_getfree(SDPath, &fre_clust, &fsp) == FR_OK) {
    uint32_t fre_sect = (uint32_t)fre_clust * fsp->csize;
    uart_log("free: %lu MiB\r\n", (unsigned long)(fre_sect / 2048UL));
  }

  /* --- long filename, only legal because LFN is on for exFAT --- */
  const char *fn = "sheppard_bringup_log.txt";

  fr = f_open(&g_fil, fn, FA_CREATE_ALWAYS | FA_WRITE);
  uart_log("f_open(w) -> %d\r\n", fr);
  if (fr == FR_OK) {
    fr = f_write(&g_fil, "sheppard sd ok\r\n", 16, &bw);
    uart_log("f_write -> %d  bw=%u\r\n", fr, bw);
    f_close(&g_fil);
  }

  /* --- read back and verify --- */
  fr = f_open(&g_fil, fn, FA_READ);
  if (fr == FR_OK) {
    /* FSIZE_t is 64-bit once exFAT is on; nano.specs printf has no %llu,
       so cast — fine for anything under 4 GiB. */
    uart_log("f_size = %lu B\r\n", (unsigned long)f_size(&g_fil));
    f_read(&g_fil, rd, sizeof rd - 1, &br);
    f_close(&g_fil);
    uart_log("readback (%u B): %s", br, rd);
    uart_log("verify: %s\r\n",
             (br == 16 && rd[0] == 's' && rd[13] == 'k') ? "PASS" : "FAIL");
  }

  /* --- sustained write throughput --- */
  for (int i = 0; i < (int)sizeof g_blk; i++) g_blk[i] = (uint8_t)i;
  fr = f_open(&g_fil, "throughput.bin", FA_CREATE_ALWAYS | FA_WRITE);
  if (fr == FR_OK) {
    uint32_t t0 = HAL_GetTick();
    for (int i = 0; i < 128; i++) {                 /* 128 x 4 KiB = 512 KiB */
      if (f_write(&g_fil, g_blk, sizeof g_blk, &bw) != FR_OK || bw != sizeof g_blk) {
        uart_log("write stalled at chunk %d\r\n", i);
        break;
      }
    }
    f_sync(&g_fil);
    uint32_t dt = HAL_GetTick() - t0;
    f_close(&g_fil);
    uart_log("512 KiB in %lu ms -> %lu KiB/s\r\n",
              (unsigned long)dt, (unsigned long)(512UL * 1000UL / (dt ? dt : 1)));
  }

  f_mount(NULL, SDPath, 0);       /* unmount cleanly */
  uart_log("fs_test done\r\n");
}


/* ===================== ISM330DHCX ===================== */
/* Same SPI convention as the ICM, so icm_write8 / icm_burst_read are reused. */

static void ism_configure(const bus_t *b)
{
  icm_write8(b, ISM_CTRL3_C,  ISM_CTRL3_C_VAL);   /* BDU + auto-increment */
  icm_write8(b, ISM_CTRL1_XL, ISM_CTRL1_XL_VAL);  /* ±16 g,     104 Hz */
  icm_write8(b, ISM_CTRL2_G,  ISM_CTRL2_G_VAL);   /* ±2000 dps, 104 Hz */
  HAL_Delay(100);   /* gyro turn-on is up to ~70 ms on this family */
  ism_enable_drdy(b);
}

static void ism_mvp_log(const bus_t *b, int idx)
{
  uint8_t c1 = spi_read8(b, ISM_CTRL1_XL);
  uint8_t c2 = spi_read8(b, ISM_CTRL2_G);
  uart_log("bus%d cfg: CTRL1_XL=0x%02X CTRL2_G=0x%02X\r\n", idx + 1, c1, c2);

  uint8_t d[14];
  icm_burst_read(b, ISM_OUT_TEMP_L, d, 14);      /* little-endian throughout */

  int16_t traw = (int16_t)(d[0]  | (d[1]  << 8));
  int16_t gx   = (int16_t)(d[2]  | (d[3]  << 8));
  int16_t gy   = (int16_t)(d[4]  | (d[5]  << 8));
  int16_t gz   = (int16_t)(d[6]  | (d[7]  << 8));
  int16_t ax   = (int16_t)(d[8]  | (d[9]  << 8));
  int16_t ay   = (int16_t)(d[10] | (d[11] << 8));
  int16_t az   = (int16_t)(d[12] | (d[13] << 8));

  /* temp degC = traw/256 + 25 ; gyro 70 mdps/LSB ; accel 0.488 mg/LSB */
  uart_log("bus%d ISM raw: T=%d  A=[%d %d %d]  G=[%d %d %d]\r\n",
            idx + 1, traw, ax, ay, az, gx, gy, gz);
}

/* ========================= BMI323 ========================= */

static void bmi_write16(const bus_t *b, uint8_t reg, uint16_t val)
{
  uint8_t tx[3] = { (uint8_t)(reg & 0x7FU),
                    (uint8_t)(val & 0xFFU),
                    (uint8_t)(val >> 8) };
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_RESET);
  HAL_SPI_Transmit(b->hspi, tx, 3, SPI_TMO);
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_SET);
}

static uint16_t bmi_read16(const bus_t *b, uint8_t reg)
{
  uint8_t tx[4] = { (uint8_t)(reg | 0x80U), 0, 0, 0 };
  uint8_t rx[4] = { 0 };
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_RESET);
  HAL_SPI_TransmitReceive(b->hspi, tx, rx, 4, SPI_TMO);
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_SET);
  return (uint16_t)(rx[2] | (rx[3] << 8));       /* rx[1] = dummy */
}

/* nwords <= 7 (buffer is 2 + 14 bytes) */
static void bmi_burst16(const bus_t *b, uint8_t reg, uint16_t *dst, uint8_t nwords)
{
  uint8_t tx[2 + 14] = { 0 };
  uint8_t rx[2 + 14] = { 0 };
  tx[0] = (uint8_t)(reg | 0x80U);
  uint16_t len = (uint16_t)(2 + 2 * nwords);
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_RESET);
  HAL_SPI_TransmitReceive(b->hspi, tx, rx, len, SPI_TMO);
  HAL_GPIO_WritePin(b->cs_port, b->cs_pin, GPIO_PIN_SET);
  for (uint8_t i = 0; i < nwords; i++)
    dst[i] = (uint16_t)(rx[2 + 2 * i] | (rx[3 + 2 * i] << 8));
}

static void bmi_configure(const bus_t *b)
{
  bmi_write16(b, BMI_ACC_CONF, BMI_ACC_CONF_VAL);
  bmi_write16(b, BMI_GYR_CONF, BMI_GYR_CONF_VAL);
  HAL_Delay(100);
  bmi_enable_drdy(b);
}

static void bmi_mvp_log(const bus_t *b, int idx)
{
  uart_log("bus%d cfg: ACC_CONF=0x%04X GYR_CONF=0x%04X\r\n",
            idx + 1, bmi_read16(b, BMI_ACC_CONF), bmi_read16(b, BMI_GYR_CONF));

  uint16_t w[7];
  bmi_burst16(b, BMI_ACC_X, w, 7);

  int16_t ax = (int16_t)w[0], ay = (int16_t)w[1], az = (int16_t)w[2];
  int16_t gx = (int16_t)w[3], gy = (int16_t)w[4], gz = (int16_t)w[5];
  int16_t traw = (int16_t)w[6];

  /* temp degC = traw/512 + 23 ; gyro 16.384 LSB/dps ; accel 2048 LSB/g */
  uart_log("bus%d BMI raw: T=%d  A=[%d %d %d]  G=[%d %d %d]\r\n",
            idx + 1, traw, ax, ay, az, gx, gy, gz);
}

/* ===================== dispatcher ===================== */

static void sensor_configure(const bus_t *b)
{
  if      (spi_read8(b, 0x75) == 0x47) icm_configure_matched(b);
  else if (spi_read8(b, 0x0F) == 0x6B) ism_configure(b);
  else if (bmi323_chipid(b)   == 0x43) bmi_configure(b);
}

static void sensor_mvp_log(const bus_t *b, int idx)
{
  if      (spi_read8(b, 0x75) == 0x47) icm_mvp_log(b, idx);
  else if (spi_read8(b, 0x0F) == 0x6B) ism_mvp_log(b, idx);
  else if (bmi323_chipid(b)   == 0x43) bmi_mvp_log(b, idx);
  else uart_log("bus%d: no known sensor\r\n", idx + 1);
}


static void icm_bank(const bus_t *b, uint8_t bank)
{
  icm_write8(b, ICM_REG_BANK_SEL, (uint8_t)(bank & 0x07U));
}

/* Read-modify-write: several fields in 0x51/0x53 (the DEC2_M2_ORD bits) have
   required non-zero values, so a blind full-register write would clobber them. */
static void icm_rmw(const bus_t *b, uint8_t reg, uint8_t mask, uint8_t val)
{
  uint8_t v = spi_read8(b, reg);
  icm_write8(b, reg, (uint8_t)((v & (uint8_t)~mask) | (val & mask)));
}

static void icm_configure_matched(const bus_t *b)
{
  /* 1. sensors OFF before touching bank-1/2 static registers */
  icm_write8(b, ICM_PWR_MGMT0, 0x00);
  HAL_Delay(1);

  /* 2. gyro AAF -> minimum cutoff (bank 1) */
  icm_bank(b, 1);
  icm_write8(b, ICM_GYRO_CFG_STATIC3, (uint8_t)(ICM_AAF_DELT & 0x3FU));
  icm_write8(b, ICM_GYRO_CFG_STATIC4, (uint8_t)(ICM_AAF_DELTSQR & 0xFFU));
  icm_write8(b, ICM_GYRO_CFG_STATIC5,
             (uint8_t)(((ICM_AAF_BITSHIFT & 0x0FU) << 4)
                       | ((ICM_AAF_DELTSQR >> 8) & 0x0FU)));

  /* 3. accel AAF -> same cutoff (bank 2). DELT occupies [6:1]; bit0 = AAF_DIS = 0.
        [VERIFY] the [6:1] placement — I confirmed the DELTSQR/BITSHIFT fields
        from the datasheet but not this one.                                 */
  icm_bank(b, 2);
  icm_write8(b, ICM_ACCEL_CFG_STATIC2, (uint8_t)((ICM_AAF_DELT & 0x3FU) << 1));
  icm_write8(b, ICM_ACCEL_CFG_STATIC3, (uint8_t)(ICM_AAF_DELTSQR & 0xFFU));
  icm_write8(b, ICM_ACCEL_CFG_STATIC4,
             (uint8_t)(((ICM_AAF_BITSHIFT & 0x0FU) << 4)
                       | ((ICM_AAF_DELTSQR >> 8) & 0x0FU)));

  icm_bank(b, 0);

  /* 4. UI filter -> ODR/2 both channels, 1st order */
  icm_write8(b, ICM_GYRO_ACCEL_CONFIG0, ICM_UI_BW_ODR_OVER_2);
  icm_rmw(b, ICM_GYRO_CONFIG1,  0x0C, 0x00);   /* GYRO_UI_FILT_ORD  = 1st  */
  icm_rmw(b, ICM_ACCEL_CONFIG1, 0x18, 0x00);   /* ACCEL_UI_FILT_ORD = 1st  */

  /* 5. sensors ON, then ODR/FSR last */
  icm_write8(b, ICM_PWR_MGMT0, 0x0F);
  HAL_Delay(1);
  icm_write8(b, ICM_GYRO_CONFIG0,  ICM_FS_MAX_ODR_100HZ);
  icm_write8(b, ICM_ACCEL_CONFIG0, ICM_FS_MAX_ODR_100HZ);
  HAL_Delay(50);
  icm_enable_drdy(b);
}




/* CDC_Transmit_HS dereferences pClassData without a NULL check in several
   CubeMX versions -> hard fault if called before enumeration. Guard it. */
static int cdc_write(const uint8_t *buf, uint16_t len)
{
  if (hUsbDeviceHS.dev_state != USBD_STATE_CONFIGURED) return -1;
  uint32_t t0 = HAL_GetTick();
  for (;;) {
    uint8_t r = CDC_Transmit_HS((uint8_t *)buf, len);
    if (r == USBD_OK)  return 0;
    if (r != USBD_BUSY) return -1;         /* FAIL / EMEM */
    if (HAL_GetTick() - t0 > 100U) return -1;   /* host not draining */
  }
}

/* cdc_log() and usb_report() removed: console_printf() and the built-in
   `usb` command in console.c do the same jobs against both sinks. */



static void cdc_burst(uint32_t nchunks)
{
  static uint8_t blk[512];                /* static: 1 KiB stack won't take this */
  for (int i = 0; i < 512; i++) blk[i] = (uint8_t)i;

  uart_log("cdc burst start: %lu chunks\r\n", (unsigned long)nchunks);
  uint32_t t0 = HAL_GetTick(), ok = 0;
  for (uint32_t i = 0; i < nchunks; i++) {
    blk[0] = (uint8_t)i;                  /* chunk index, for loss detection */
    blk[1] = (uint8_t)(i >> 8);
    if (cdc_write(blk, sizeof blk) == 0) ok++;
  }
  uint32_t dt = HAL_GetTick() - t0;
  uart_log("cdc burst: %lu/%lu chunks in %lu ms -> %lu KiB/s\r\n",
            (unsigned long)ok, (unsigned long)nchunks, (unsigned long)dt,
            (unsigned long)(ok / 2UL * 1000UL / (dt ? dt : 1)));
}


static void rtc_init_once(void)
{
  if (HAL_RTCEx_BKUPRead(&hrtc, RTC_BKP_DR0) == RTC_MAGIC) {
    uart_log("RTC already set\r\n");
    return;
  }

  /* Seed from build time. Compile-time only — replace with a host-set value
     for anything where absolute accuracy matters. __TIME__ is "HH:MM:SS". */
  RTC_TimeTypeDef t = {0};
  RTC_DateTypeDef d = {0};
  t.Hours   = (__TIME__[0]-'0')*10 + (__TIME__[1]-'0');
  t.Minutes = (__TIME__[3]-'0')*10 + (__TIME__[4]-'0');
  t.Seconds = (__TIME__[6]-'0')*10 + (__TIME__[7]-'0');
  t.DayLightSaving = RTC_DAYLIGHTSAVING_NONE;
  t.StoreOperation = RTC_STOREOPERATION_RESET;

  d.Date  = 26;  d.Month = RTC_MONTH_JULY;  d.Year = 26;   /* YY, 2000-based */
  d.WeekDay = RTC_WEEKDAY_SUNDAY;

  if (HAL_RTC_SetTime(&hrtc, &t, RTC_FORMAT_BIN) != HAL_OK) { uart_log("RTC SetTime FAIL\r\n"); return; }
  if (HAL_RTC_SetDate(&hrtc, &d, RTC_FORMAT_BIN) != HAL_OK) { uart_log("RTC SetDate FAIL\r\n"); return; }

  HAL_RTCEx_BKUPWrite(&hrtc, RTC_BKP_DR0, RTC_MAGIC);
  uart_log("RTC seeded from build time\r\n");
}

static void rtc_print(void)
{
  RTC_TimeTypeDef t; RTC_DateTypeDef d;
  HAL_RTC_GetTime(&hrtc, &t, RTC_FORMAT_BIN);
  HAL_RTC_GetDate(&hrtc, &d, RTC_FORMAT_BIN);   /* MUST follow GetTime */
  uart_log("RTC: 20%02u-%02u-%02u %02u:%02u:%02u\r\n",
            d.Year, d.Month, d.Date, t.Hours, t.Minutes, t.Seconds);
}



/* ---- data-ready enable ---- */

static void icm_enable_drdy(const bus_t *b)
{
  icm_write8(b, ICM_INT_CONFIG,  0x03);        /* INT1 push-pull, active high, pulsed */
  icm_rmw   (b, ICM_INT_CONFIG1, 0x10, 0x00);  /* clear INT_ASYNC_RESET (bit4);
                                                  reset default is 1, must be 0     */
  icm_write8(b, ICM_INT_SOURCE0, 0x08);        /* UI_DRDY_INT1_EN */
}

static void ism_enable_drdy(const bus_t *b)
{
  icm_rmw(b, ISM_COUNTER_BDR_REG1, ISM_DRDY_PULSED, ISM_DRDY_PULSED); /* pulse, not level */
  icm_write8(b, ISM_INT1_CTRL, 0x02);   /* INT1_DRDY_G */
}

static void bmi_enable_drdy(const bus_t *b)
{
  bmi_write16(b, BMI_IO_INT_CTRL, 0x0005);     /* INT1 output enable + active high */
  bmi_write16(b, BMI_INT_MAP2,    0x0100);     /* gyr_drdy -> INT1, bits [9:8] = 01 */
}


/* ===================== console commands ===================== */

static void cmd_scan(int argc, char **argv)
{
  (void)argc; (void)argv;
  scan_all_buses();
  for (int i = 0; i < 4; i++) sensor_mvp_log(&g_buses[i], i);
}

static void cmd_sd(int argc, char **argv)
{
  (void)argc; (void)argv;
  fs_test();
}

static void cmd_burst(int argc, char **argv)
{
  uint32_t n = 200;
  if (argc >= 2) {
    long v = strtol(argv[1], NULL, 10);
    if (v > 0 && v <= 100000L) n = (uint32_t)v;
  }
  cdc_burst(n);
}

/* Replaces the fixed-width byte-indexing parser of TN-16 SS8.4, which indexed
   absolute positions in the packet and produced silent garbage whenever a
   field was a character short. This one tokenises and validates ranges, and
   it no longer matters whether the host pastes or types the line. */
static void cmd_time(int argc, char **argv)
{
  int yr, mo, dy, hh, mi, ss;

  if (argc < 3 ||
      sscanf(argv[1], "%d-%d-%d", &yr, &mo, &dy) != 3 ||
      sscanf(argv[2], "%d:%d:%d", &hh, &mi, &ss) != 3) {
    console_printf("usage: time YYYY-MM-DD HH:MM:SS\r\n");
    return;
  }

  if (yr < 2000 || yr > 2099 || mo < 1 || mo > 12 || dy < 1 || dy > 31 ||
      hh < 0 || hh > 23 || mi < 0 || mi > 59 || ss < 0 || ss > 59) {
    console_printf("time: value out of range\r\n");
    return;
  }

  RTC_TimeTypeDef t = {0};
  RTC_DateTypeDef d = {0};
  t.Hours   = (uint8_t)hh;
  t.Minutes = (uint8_t)mi;
  t.Seconds = (uint8_t)ss;
  t.DayLightSaving = RTC_DAYLIGHTSAVING_NONE;
  t.StoreOperation = RTC_STOREOPERATION_RESET;
  d.Year    = (uint8_t)(yr - 2000);
  d.Month   = (uint8_t)mo;
  d.Date    = (uint8_t)dy;
  d.WeekDay = RTC_WEEKDAY_MONDAY;          /* not used by get_fattime */

  if (HAL_RTC_SetTime(&hrtc, &t, RTC_FORMAT_BIN) != HAL_OK ||
      HAL_RTC_SetDate(&hrtc, &d, RTC_FORMAT_BIN) != HAL_OK) {
    console_printf("time: RTC set FAILED\r\n");
    return;
  }
  HAL_RTCEx_BKUPWrite(&hrtc, RTC_BKP_DR0, RTC_MAGIC);
  rtc_print();
}

/* Counts data-ready edges over a fixed window. Two jobs at once: it validates
   every interrupt-enable register value in TN-16 SS9.2 empirically, and it
   measures each sensor's true ODR against the board oscillator (SS10.1).

   NON-BLOCKING. The first version sat in a busy-wait for the whole window and
   aborted on any received byte, which turned out to be a bad idea twice over:
   the command's own trailing newline tripped the abort, and while it spun,
   console_task() and fw_task() were not running, so the board looked hung and
   a long window could not be interrupted cleanly. Now the command only arms
   the measurement and rate_task() finishes it, so the console stays live and
   `rate 600` costs nothing.

   Resolution: +-1 count over the window. At 10 s and 100 Hz that is +-0.1 %,
   which barely resolves the 0.40 % ICM-to-ICM difference. Use `rate 600` for
   +-0.0017 % before putting a number in a record header -- TN-16 SS10.4.

   Note the measurement is now open to interference: anything you type adds
   USB traffic, and `scan` adds SPI traffic, inside the window. Leave the
   board alone while it counts if the number is going anywhere near a record
   header. */
static void cmd_rate(int argc, char **argv)
{
  if (argc >= 2 && strcmp(argv[1], "stop") == 0) {
    if (g_rate_active) { g_rate_active = 0; console_printf("rate: cancelled\r\n"); }
    else               { console_printf("rate: not running\r\n"); }
    return;
  }

  if (g_rate_active) {
    uint32_t left = g_rate_window - (HAL_GetTick() - g_rate_t0);
    console_printf("rate: already running, %lu ms left (`rate stop` to cancel)\r\n",
                   (unsigned long)left);
    return;
  }

  uint32_t window = RATE_WINDOW_MS;
  if (argc >= 2) {
    long s = strtol(argv[1], NULL, 10);
    if (s >= 1 && s <= 43200L) window = (uint32_t)s * 1000UL;
    else { console_printf("usage: rate [seconds 1..43200] | rate stop\r\n"); return; }
  }

  for (int i = 0; i < 4; i++) g_rate_c0[i] = g_drdy_count[i];
  g_rate_t0     = HAL_GetTick();
  g_rate_window = window;
  g_rate_active = 1;

  console_printf("rate: counting for %lu ms, results will follow\r\n",
                 (unsigned long)window);
}

/* Cross-checks TIM2 against SysTick. They are the same crystal via different
   dividers, so agreement proves the prescaler and the 64-bit extension, not
   the oscillator -- the true HSE tolerance still has to go in the systematics
   budget (TN-16 SS10.1). Disagreement of a few percent means the prescaler is
   wrong; a jump of ~4.29e9 us means the wrap handling is wrong. */
static void cmd_tick(int argc, char **argv)
{
  uint32_t secs = 2;
  if (argc >= 2) {
    long s = strtol(argv[1], NULL, 10);
    if (s >= 1 && s <= 600L) secs = (uint32_t)s;
  }

  uint64_t u0 = timebase_now_us();
  uint32_t m0 = HAL_GetTick();
  HAL_Delay(secs * 1000UL);
  uint64_t u1 = timebase_now_us();
  uint32_t m1 = HAL_GetTick();

  uint64_t du = u1 - u0;
  uint32_t dm = m1 - m0;

  /* parts-per-thousand deviation of TIM2 from SysTick */
  int32_t ppt = (int32_t)((int64_t)du - (int64_t)dm * 1000) * 1000
                / (int32_t)(dm ? dm * 1000 : 1);

  console_printf("tick: TIM2 %lu us over SysTick %lu ms  (dev %ld ppt)\r\n",
                 (unsigned long)du, (unsigned long)dm, (long)ppt);
  console_printf("  now=%lu:%010lu us  wraps=%lu\r\n",
                 (unsigned long)(u1 >> 32), (unsigned long)(u1 & 0xFFFFFFFFUL),
                 (unsigned long)timebase_wraps());
  if (ppt > 20 || ppt < -20)
    console_printf("  DEVIATION >2%% -- check the TIM2 prescaler "
                   "(want 31, APB1 timer clock 32 MHz)\r\n");
}

/* Completes an armed measurement. Called every main-loop iteration. */
static void rate_task(void)
{
  if (!g_rate_active) return;

  uint32_t dt = HAL_GetTick() - g_rate_t0;
  if (dt < g_rate_window) return;

  g_rate_active = 0;

  console_printf("rate: %lu ms window\r\n", (unsigned long)dt);
  for (int i = 0; i < 4; i++) {
    uint32_t dn = g_drdy_count[i] - g_rate_c0[i];
    /* 64-bit intermediate is required, not decorative: at 8 kHz over an hour
       dn reaches ~2.9e7, and dn * 1000 alone already overflows uint32_t. */
    uint32_t mhz = (uint32_t)(((uint64_t)dn * 1000000ULL) / (dt ? dt : 1U));
    console_printf("  bus%d: %lu edges -> %lu.%03lu Hz\r\n",
                   i + 1, (unsigned long)dn,
                   (unsigned long)(mhz / 1000UL),
                   (unsigned long)(mhz % 1000UL));
  }
  console_printf("  0 Hz = handler or enable register; "
                 "rate == read rate = level-mode DRDY\r\n");
}

/* Overrides the __weak HAL default. Runs in interrupt context —
   no SPI, no HAL_Delay, no uart_log in here. */
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
  /* Edge counting, for the `rate` true-ODR measurement. Cheap enough to leave
     running always -- 25 to 8000 increments per second. */
  for (int i = 0; i < 4; i++) {
    if (g_buses[i].int_pin == GPIO_Pin) {
      g_drdy_count[i]++;
      g_drdy_flag |= (1u << i);
      break;
    }
  }

  /* Then the logger. While a record is open, INT1 carries the FIFO watermark
     rather than data-ready, and this starts the DMA burst that empties it.
     Does nothing when no record is running. Kept last so the counters above
     are updated even if the sampler returns early. */
  sampler_on_int(GPIO_Pin);
}

/* USER CODE END 4 */

 /* MPU Configuration */

void MPU_Config(void)
{
  MPU_Region_InitTypeDef MPU_InitStruct = {0};

  /* Disables the MPU */
  HAL_MPU_Disable();

  /** Initializes and configures the Region and the memory to be protected
  */
  MPU_InitStruct.Enable = MPU_REGION_ENABLE;
  MPU_InitStruct.Number = MPU_REGION_NUMBER0;
  MPU_InitStruct.BaseAddress = 0x0;
  MPU_InitStruct.Size = MPU_REGION_SIZE_4GB;
  MPU_InitStruct.SubRegionDisable = 0x87;
  MPU_InitStruct.TypeExtField = MPU_TEX_LEVEL0;
  MPU_InitStruct.AccessPermission = MPU_REGION_NO_ACCESS;
  MPU_InitStruct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;
  MPU_InitStruct.IsShareable = MPU_ACCESS_SHAREABLE;
  MPU_InitStruct.IsCacheable = MPU_ACCESS_NOT_CACHEABLE;
  MPU_InitStruct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;

  HAL_MPU_ConfigRegion(&MPU_InitStruct);
  /* Enables the MPU */
  HAL_MPU_Enable(MPU_PRIVILEGED_DEFAULT);

}

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
	  error_dump();
	  __disable_irq();
	  while (1)
	  {
	  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
