/**
  ******************************************************************************
  * @file    imu_icm42688.h
  * @brief   ICM-42688-P driver: configuration, 16-bit registers, hi-res FIFO.
  *
  * All register values below are taken from DS-000347 **Rev 1.6**
  * (Misc/Datasheets/), read directly. The corpus was built against v1.2, which
  * is marked pre-production -- the ** critical-path action "re-verify every
  * datasheet value against the current revision" applies to anything here that
  * disagrees with an older note.
  *
  * DESIGN RULE: every configuration write is read back and asserted. TN-16
  * carries six open [verify] items that exist because a write was assumed to
  * have landed. A wrong value now fails loudly at bring-up instead of quietly
  * corrupting a 20-minute record.
  ******************************************************************************
  */

#ifndef IMU_ICM42688_H
#define IMU_ICM42688_H

#include <stdint.h>
#include "bus.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ==========================================================================
 * Register map, DS-000347 Rev 1.6 section 14  [fact]
 * ========================================================================== */

/* --- bank 0 --------------------------------------------------------------- */
#define ICM_DEVICE_CONFIG        0x11U   /* SPI_MODE, SOFT_RESET_CONFIG        */
#define ICM_DRIVE_CONFIG         0x13U
#define ICM_INT_CONFIG           0x14U   /* INT1/INT2 mode, drive, polarity    */
#define ICM_FIFO_CONFIG          0x16U   /* [7:6] FIFO_MODE                    */
#define ICM_TEMP_DATA1           0x1DU
#define ICM_ACCEL_DATA_X1        0x1FU   /* 6 B accel, big-endian              */
#define ICM_GYRO_DATA_X1         0x25U   /* 6 B gyro,  big-endian              */
#define ICM_INT_STATUS           0x2DU   /* R/C                                */
#define ICM_FIFO_COUNTH          0x2EU   /* reading H latches both             */
#define ICM_FIFO_COUNTL          0x2FU
#define ICM_FIFO_DATA            0x30U   /* streams; address does not advance  */
#define ICM_SIGNAL_PATH_RESET    0x4BU   /* bit1 FIFO_FLUSH                    */
#define ICM_INTF_CONFIG0         0x4CU   /* reset 0x30 -- see icm_check_endian */
#define ICM_INTF_CONFIG1         0x4DU
#define ICM_PWR_MGMT0            0x4EU
#define ICM_GYRO_CONFIG0         0x4FU   /* [7:5] FS_SEL, [3:0] ODR            */
#define ICM_ACCEL_CONFIG0        0x50U
#define ICM_GYRO_CONFIG1         0x51U
#define ICM_GYRO_ACCEL_CONFIG0   0x52U   /* [7:4] ACCEL UI BW, [3:0] GYRO UI BW*/
#define ICM_ACCEL_CONFIG1        0x53U
#define ICM_TMST_CONFIG          0x54U
#define ICM_FIFO_CONFIG1         0x5FU
#define ICM_FIFO_CONFIG2         0x60U   /* FIFO_WM[7:0]                       */
#define ICM_FIFO_CONFIG3         0x61U   /* [3:0] FIFO_WM[11:8]                */
#define ICM_INT_CONFIG0          0x63U
#define ICM_INT_CONFIG1          0x64U
#define ICM_INT_SOURCE0          0x65U
#define ICM_WHO_AM_I             0x75U   /* 0x47                               */
#define ICM_REG_BANK_SEL         0x76U

/* --- bank 1 (gyro AAF) ----------------------------------------------------- */
#define ICM_GYRO_CFG_STATIC3     0x0CU   /* [5:0] GYRO_AAF_DELT                */
#define ICM_GYRO_CFG_STATIC4     0x0DU   /* DELTSQR[7:0]                       */
#define ICM_GYRO_CFG_STATIC5     0x0EU   /* [7:4] BITSHIFT, [3:0] DELTSQR[11:8]*/

/* --- bank 4 (OFFSET_USER) --------------------------------------------------
 *
 * The digital phase ladder of TN-13 section 4.3. Gyro offsets are 12-bit
 * signed, packed three-and-a-half registers wide because X and Y share the
 * nibbles of OFFSET_USER1.
 *
 *   OFFSET_USER0  GYRO_X_OFFUSER[7:0]
 *   OFFSET_USER1  GYRO_Y_OFFUSER[11:8] << 4 | GYRO_X_OFFUSER[11:8]
 *   OFFSET_USER2  GYRO_Y_OFFUSER[7:0]
 *   OFFSET_USER3  GYRO_Z_OFFUSER[7:0]
 *   OFFSET_USER4  ACCEL_X_OFFUSER[11:8] << 4 | GYRO_Z_OFFUSER[11:8]
 *
 * RESOLUTION IS THE WHOLE QUESTION. DS-000347 gives 1/32 dps per step over
 * +/-64 dps, so one step is
 *
 *     (1/32) / (2000/32768) = 0.512 Delta   exactly
 *
 * which is COARSER than one quantiser LSB. A naive 12-step ladder therefore
 * does not sweep phase -- it lands on two clusters. But 0.512 = 64/125, so
 * k steps give phase (64k mod 125)/125, and 125 distinct phases are reachable
 * at a spacing of 0.008 Delta. Choosing k = 84m mod 125 hits phase m/125,
 * because 84 is the inverse of 64 modulo 125. That turns a coarse register
 * into a fine phase control, and it is why the ladder is specified as a list
 * of step counts rather than a uniform increment.
 *
 * The 1/32 dps figure must be CONFIRMED on hardware before the ladder is
 * trusted: apply a known step, measure the shift in mu from the 19-bit stream,
 * and check it against 0.512 Delta. That measurement also tests TN-13's
 * assumption that the offset is applied pre-register on the fine lattice,
 * which is the ladder's entire premise.
 * -------------------------------------------------------------------------- */
#define ICM_OFFSET_USER0         0x77U
#define ICM_OFFSET_USER1         0x78U
#define ICM_OFFSET_USER2         0x79U
#define ICM_OFFSET_USER3         0x7AU
#define ICM_OFFSET_USER4         0x7BU

/** Nominal step size in units of the 16-bit LSB. Verify before relying on it. */
#define ICM_OFFSET_STEP_DELTA    0.512

/* --- bank 2 (accel AAF) ---------------------------------------------------- */
#define ICM_ACCEL_CFG_STATIC2    0x03U   /* [6:1] ACCEL_AAF_DELT, [0] AAF_DIS  */
#define ICM_ACCEL_CFG_STATIC3    0x04U
#define ICM_ACCEL_CFG_STATIC4    0x05U

#define ICM_WHO_AM_I_VALUE       0x47U

/* --- bit fields ------------------------------------------------------------ */

/* FIFO_CONFIG [7:6]  DS Rev 1.6 section 14.4 */
#define ICM_FIFO_MODE_BYPASS     (0U << 6)
#define ICM_FIFO_MODE_STREAM     (1U << 6)   /* newest kept, oldest overwritten */
#define ICM_FIFO_MODE_STOP_FULL  (2U << 6)

/* FIFO_CONFIG1 */
#define ICM_FIFO_RESUME_PARTIAL_RD  (1U << 6)
#define ICM_FIFO_WM_GT_TH           (1U << 5)
#define ICM_FIFO_HIRES_EN           (1U << 4)
#define ICM_FIFO_TMST_FSYNC_EN      (1U << 3)
#define ICM_FIFO_TEMP_EN            (1U << 2)
#define ICM_FIFO_GYRO_EN            (1U << 1)
#define ICM_FIFO_ACCEL_EN           (1U << 0)

/* SIGNAL_PATH_RESET */
#define ICM_ABORT_AND_RESET         (1U << 3)
#define ICM_TMST_STROBE             (1U << 2)
#define ICM_FIFO_FLUSH              (1U << 1)

/* INT_SOURCE0  DS Rev 1.6 section 14.51, reset 0x10 */
#define ICM_UI_DRDY_INT1_EN         (1U << 3)
#define ICM_FIFO_THS_INT1_EN        (1U << 2)
#define ICM_FIFO_FULL_INT1_EN       (1U << 1)

/* INT_STATUS  DS Rev 1.6 section 14.21, read-to-clear */
#define ICM_INT_DATA_RDY            (1U << 3)
#define ICM_INT_FIFO_THS            (1U << 2)
#define ICM_INT_FIFO_FULL           (1U << 1)

/* FIFO header byte  DS Rev 1.6 section 6.2 */
#define ICM_HDR_MSG                 (1U << 7)   /* 1 = FIFO empty              */
#define ICM_HDR_ACCEL               (1U << 6)
#define ICM_HDR_GYRO                (1U << 5)
#define ICM_HDR_20BIT               (1U << 4)   /* new, valid extended data    */

/* Packet 4, hi-res: header + 6 accel + 6 gyro + 2 temp + 2 tmst + 3 extension */
#define ICM_PACKET4_LEN             20U

/* ==========================================================================
 * Configuration
 * ========================================================================== */

/* AAF settings, from the 3 dB bandwidth table in DS Rev 1.6 section 5.3.
 * Both modes WRITE the registers -- an earlier version left them untouched
 * for "native", which silently inherited whatever the previous configuration
 * had set and made the two modes indistinguishable.
 *
 *   BW(Hz)  DELT  DELTSQR  BITSHIFT
 *      42      1        1        15   <- the minimum the part supports
 *     258      6       36        10
 *     585     13      170         8   <- GYRO_CONFIG_STATIC3 reset value 0x0D
 *
 * TN-16 section 5.1 states the default is "~258 Hz". It is 585 Hz.
 * TN-16 open item 1 asked whether 1/1/15 really gives 42 Hz. It does. */
typedef enum {
  ICM_AAF_DEFAULT = 0,  /* 585 Hz -- the power-on value, written explicitly  */
  ICM_AAF_FLOOR         /* 42 Hz  -- the "matched" config of TN-16 5.4       */
} icm_aaf_mode_t;

#define ICM_AAF_FLOOR_DELT        1U
#define ICM_AAF_FLOOR_DELTSQR     1U
#define ICM_AAF_FLOOR_BITSHIFT    15U

#define ICM_AAF_DEFAULT_DELT      13U
#define ICM_AAF_DEFAULT_DELTSQR   170U
#define ICM_AAF_DEFAULT_BITSHIFT  8U

typedef struct {
  uint8_t        odr_code;    /* GYRO_CONFIG0[3:0]; 0x6=25, 0x7=50, 0x8=100  */
  uint8_t        fs_sel;      /* GYRO_CONFIG0[7:5]; 0 = +-2000 dps           */
  uint8_t        ui_filt_bw;  /* GYRO_ACCEL_CONFIG0[3:0]; 0 tracks ODR       */
  icm_aaf_mode_t aaf;
  uint8_t        hires;       /* 1 = 20-bit FIFO packets (forces +-2000 dps) */
  uint16_t       watermark;   /* FIFO watermark in *bytes*                   */
} icm_config_t;

/* ODR codes, DS Rev 1.6 section 14.37. 12.5 Hz is deliberately absent: TN-14
   section 1.3 drops it (identical NBW to 25 Hz, and 53% aliased). */
#define ICM_ODR_1KHZ    0x06U
#define ICM_ODR_200HZ   0x07U
#define ICM_ODR_100HZ   0x08U
#define ICM_ODR_50HZ    0x09U
#define ICM_ODR_25HZ    0x0AU
#define ICM_ODR_8KHZ    0x03U
#define ICM_ODR_500HZ   0x0FU

/* ==========================================================================
 * Decoded hi-res packet
 * ========================================================================== */

typedef struct {
  uint8_t  header;
  int32_t  gyro[3];      /* 20-bit signed, sign-extended                     */
  int32_t  accel[3];
  int16_t  temp;
  uint16_t tmst;

  /* Bits [19:4] of each gyro field, i.e. bytes 0x07/0x08 concatenated.
     If the 16-bit register is a truncation of the fine word these are
     numerically identical to it -- which is the whole of V0.4. */
  int16_t  gyro_hi16[3];
} icm_packet_t;

/* ==========================================================================
 * API
 * ========================================================================== */

int  icm_probe(bus_slot_t slot);                       /* WHO_AM_I           */
int  icm_soft_reset(bus_slot_t slot);
int  icm_configure(bus_slot_t slot, const icm_config_t *cfg);
int  icm_check_endian(bus_slot_t slot);                /* INTF_CONFIG0 == 0x30 */

int  icm_fifo_flush(bus_slot_t slot);
int  icm_fifo_count(bus_slot_t slot, uint16_t *bytes);
int  icm_fifo_read(bus_slot_t slot, uint8_t *dst, uint16_t bytes);

/** Decode one 20-byte Packet 4. Returns 0, or -1 if the header says empty. */
int  icm_packet4_decode(const uint8_t *p, icm_packet_t *out);

/** Burst-read the 16-bit registers: temp(2) accel(6) gyro(6) from 0x1D. */
int  icm_read_regs(bus_slot_t slot, int16_t *temp,
                   int16_t accel[3], int16_t gyro[3]);

/** ODR in Hz -> GYRO_CONFIG0[3:0] code. Returns 0xFF if unsupported.
    12.5 Hz is deliberately rejected: TN-14 section 1.3 drops it (identical
    NBW to 25 Hz, and 53% aliased). */
uint8_t icm_odr_code(long hz);

int  icm_read8(bus_slot_t slot, uint8_t reg, uint8_t *val);
int  icm_write8(bus_slot_t slot, uint8_t reg, uint8_t val);

/** Write then read back; returns -1 and logs if the read-back disagrees. */
int  icm_write8_verify(bus_slot_t slot, uint8_t reg, uint8_t val);

/**
  * @brief  Apply a gyro OFFSET_USER step to all three axes, in bank 4.
  *
  *         Written to X, Y and Z together: the phase axis is a property of the
  *         measurement rather than of one channel, and leaving two axes at zero
  *         would mean the three replicates were no longer replicates.
  *
  * @param  steps  12-bit signed, -2048..2047. One step is nominally 0.512 of a
  *                16-bit LSB -- see the note above ICM_OFFSET_USER0.
  * @retval 0 on success with read-back verified, -1 otherwise.
  */
int  icm_set_gyro_offset(bus_slot_t slot, int16_t steps);

/**
  * @brief  Step count landing closest to a target phase.
  *
  *         Solves (64k mod 125)/125 ~= num/den using the inverse of 64 modulo
  *         125. Exposed so the console can print the ladder and a reviewer can
  *         check it against the arithmetic documented at ICM_OFFSET_USER0.
  */
int16_t icm_offset_for_phase(int num, int den);

/** Register the `icm` and `fifo` console commands. */
void icm_console_init(void);

#ifdef __cplusplus
}
#endif

#endif /* IMU_ICM42688_H */
