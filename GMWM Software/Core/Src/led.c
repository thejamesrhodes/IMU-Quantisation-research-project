/**
  ******************************************************************************
  * @file    led.c
  * @brief   Status indication. See led.h for the assignment and the rationale.
  ******************************************************************************
  */

#include "led.h"
#include "timebase.h"
#include "sheppard_config.h"
#include "main.h"

/* Polarity lives in sheppard_config.h. Getting it backwards gives an indicator
   that is on when it should be off, which is worse than no indicator at all. */
#if SHEPPARD_LED_ACTIVE_LOW
  #define LED_ON   GPIO_PIN_RESET
  #define LED_OFF  GPIO_PIN_SET
#else
  #define LED_ON   GPIO_PIN_SET
  #define LED_OFF  GPIO_PIN_RESET
#endif

static volatile led_mode_t s_mode;
static volatile uint8_t    s_fault;
static volatile uint8_t    s_gate_active;
static volatile uint8_t    s_gate_within;
static uint64_t            s_t0;

static inline void put(GPIO_TypeDef *port, uint16_t pin, int on)
{
  HAL_GPIO_WritePin(port, pin, on ? LED_ON : LED_OFF);
}

void led_init(void)
{
  s_mode = LED_MODE_IDLE;
  s_fault = 0U;
  s_gate_active = 0U;
  s_gate_within = 1U;
  s_t0 = timebase_now_us();

  put(LED_1_GPIO_Port, LED_1_Pin, 0);
  put(LED_2_GPIO_Port, LED_2_Pin, 0);
  put(LED_3_GPIO_Port, LED_3_Pin, 0);
}

void led_set_mode(led_mode_t mode)   { s_mode = mode; }
void led_fault(void)                 { s_fault = 1U; }
void led_clear_faults(void)          { s_fault = 0U; }
int  led_faulted(void)               { return (int)s_fault; }

void led_thermal(int active, int within)
{
  s_gate_active = active ? 1U : 0U;
  s_gate_within = within ? 1U : 0U;
}

int sheppard_vbus_present(void)
{
  /* PB13 carries VBUS through a divider; high means the host is supplying 5 V.
     Lives here rather than in a header as an inline so there is exactly one
     definition of "is USB powering this board", used by both the record header
     and any future power-path logic. */
  return (HAL_GPIO_ReadPin(VBUS_GPIO_Port, VBUS_Pin) == GPIO_PIN_SET) ? 1 : 0;
}

void led_task(void)
{
  /* Phase within a 2 s cycle, in milliseconds. Derived from TIM2 rather than
     HAL_GetTick so the indicator keeps working inside code that runs with
     SysTick starved. */
  uint32_t ms = (uint32_t)(((timebase_now_us() - s_t0) / 1000ULL) % 2000ULL);

  /* --- LED1: alive ------------------------------------------------------ */
  /*
   * Patterns, not brightness. The first version breathed with software PWM,
   * which is unreadable when the four LEDs sit side by side: a dim LED next to
   * a bright one just looks like a dim LED, and you cannot tell "idle" from
   * "half-broken". Distinct RHYTHMS survive that, and they survive being seen
   * out of the corner of your eye from across the room, which is the actual
   * use case at 8 a.m. after an unattended run.
   *
   *   idle      one short flash every 2 s          "alive, doing nothing"
   *   record    even 2 Hz square                   "working"
   *   sequence  three quick flashes, then a gap    "working through a list"
   *   busy      8 Hz stutter                       "do not unplug"
   */
  int alive;
  switch (s_mode)
  {
    case LED_MODE_REC:
      alive = ((ms % 500U) < 250U);                  /* 2 Hz, 50% duty     */
      break;

    case LED_MODE_SEQ:
      /* Three 90 ms flashes inside the first 600 ms, then 1.4 s dark. */
      alive = ((ms < 600U) && ((ms % 200U) < 90U));
      break;

    case LED_MODE_BUSY:
      alive = ((ms % 125U) < 62U);                   /* 8 Hz               */
      break;

    default:
      alive = (ms < 80U);                            /* one blip per 2 s   */
      break;
  }
  put(LED_1_GPIO_Port, LED_1_Pin, alive);

  /* --- LED2: integrity, latching ---------------------------------------- */
  put(LED_2_GPIO_Port, LED_2_Pin, (int)s_fault);

  /* --- LED3: thermal gate ----------------------------------------------- */
  int therm;
  if (!s_gate_active)
  {
    therm = 0;                       /* no gate applies -- nothing to say  */
  }
  else if (s_gate_within)
  {
    therm = 1;                       /* steady: inside the gate            */
  }
  else
  {
    therm = ((ms % 500U) < 250U);    /* 2 Hz blink: drifting too fast      */
  }
  put(LED_3_GPIO_Port, LED_3_Pin, therm);
}
