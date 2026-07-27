/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
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

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f7xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define SCK_4_Pin GPIO_PIN_2
#define SCK_4_GPIO_Port GPIOE
#define INT4_1_Pin GPIO_PIN_3
#define INT4_1_GPIO_Port GPIOE
#define INT4_1_EXTI_IRQn EXTI3_IRQn
#define MISO_4_Pin GPIO_PIN_5
#define MISO_4_GPIO_Port GPIOE
#define MOSI_4_Pin GPIO_PIN_6
#define MOSI_4_GPIO_Port GPIOE
#define LSE_IN_Pin GPIO_PIN_14
#define LSE_IN_GPIO_Port GPIOC
#define LSE_OUT_Pin GPIO_PIN_15
#define LSE_OUT_GPIO_Port GPIOC
#define INT3_1_Pin GPIO_PIN_5
#define INT3_1_GPIO_Port GPIOF
#define INT3_1_EXTI_IRQn EXTI9_5_IRQn
#define SCK_3_Pin GPIO_PIN_7
#define SCK_3_GPIO_Port GPIOF
#define MISO_3_Pin GPIO_PIN_8
#define MISO_3_GPIO_Port GPIOF
#define MOSI_3_Pin GPIO_PIN_9
#define MOSI_3_GPIO_Port GPIOF
#define CS_3_Pin GPIO_PIN_10
#define CS_3_GPIO_Port GPIOF
#define HSE_IN_Pin GPIO_PIN_0
#define HSE_IN_GPIO_Port GPIOH
#define HSE_OUT_Pin GPIO_PIN_1
#define HSE_OUT_GPIO_Port GPIOH
#define TX_1_Pin GPIO_PIN_0
#define TX_1_GPIO_Port GPIOA
#define RX_1_Pin GPIO_PIN_1
#define RX_1_GPIO_Port GPIOA
#define CS_1_Pin GPIO_PIN_4
#define CS_1_GPIO_Port GPIOA
#define SCK_1_Pin GPIO_PIN_5
#define SCK_1_GPIO_Port GPIOA
#define MISO_1_Pin GPIO_PIN_6
#define MISO_1_GPIO_Port GPIOA
#define MOSI_1_Pin GPIO_PIN_7
#define MOSI_1_GPIO_Port GPIOA
#define MOSI_2_Pin GPIO_PIN_2
#define MOSI_2_GPIO_Port GPIOB
#define CS_4_Pin GPIO_PIN_7
#define CS_4_GPIO_Port GPIOE
#define LED_1_Pin GPIO_PIN_12
#define LED_1_GPIO_Port GPIOE
#define LED_2_Pin GPIO_PIN_13
#define LED_2_GPIO_Port GPIOE
#define LED_3_Pin GPIO_PIN_14
#define LED_3_GPIO_Port GPIOE
#define LED_4_Pin GPIO_PIN_15
#define LED_4_GPIO_Port GPIOE
#define VBUS_Pin GPIO_PIN_13
#define VBUS_GPIO_Port GPIOB
#define USB_D__Pin GPIO_PIN_14
#define USB_D__GPIO_Port GPIOB
#define USB_D_B15_Pin GPIO_PIN_15
#define USB_D_B15_GPIO_Port GPIOB
#define INT1_1_Pin GPIO_PIN_8
#define INT1_1_GPIO_Port GPIOA
#define INT1_1_EXTI_IRQn EXTI9_5_IRQn
#define TX_2_Pin GPIO_PIN_9
#define TX_2_GPIO_Port GPIOA
#define RX_2_Pin GPIO_PIN_10
#define RX_2_GPIO_Port GPIOA
#define SWDIO_Pin GPIO_PIN_13
#define SWDIO_GPIO_Port GPIOA
#define SWCLK_Pin GPIO_PIN_14
#define SWCLK_GPIO_Port GPIOA
#define SCK_2_Pin GPIO_PIN_10
#define SCK_2_GPIO_Port GPIOC
#define MISO_2_Pin GPIO_PIN_11
#define MISO_2_GPIO_Port GPIOC
#define INT2_1_Pin GPIO_PIN_12
#define INT2_1_GPIO_Port GPIOC
#define INT2_1_EXTI_IRQn EXTI15_10_IRQn
#define CS_2_Pin GPIO_PIN_1
#define CS_2_GPIO_Port GPIOD
#define CLK_SD_Pin GPIO_PIN_6
#define CLK_SD_GPIO_Port GPIOD
#define CMD_Pin GPIO_PIN_7
#define CMD_GPIO_Port GPIOD
#define DAT0_Pin GPIO_PIN_9
#define DAT0_GPIO_Port GPIOG
#define DAT1_Pin GPIO_PIN_10
#define DAT1_GPIO_Port GPIOG
#define DAT2_Pin GPIO_PIN_11
#define DAT2_GPIO_Port GPIOG
#define DAT3_Pin GPIO_PIN_12
#define DAT3_GPIO_Port GPIOG
#define SCL_Pin GPIO_PIN_6
#define SCL_GPIO_Port GPIOB
#define SDA_Pin GPIO_PIN_7
#define SDA_GPIO_Port GPIOB
#define CD_Pin GPIO_PIN_0
#define CD_GPIO_Port GPIOE

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
