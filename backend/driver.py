import time

from config import (I2C_ADDRESS, PWM_FREQ_HZ, PCA_RESET_CONFIRM, PCA_CONFIRM_GAP_S,
                    PCA_FREQ_BAD_BEATS, PCA_STORM_N, PCA_STORM_WINDOW_S,
                    PCA_DUTY_TOLERANCE)

_LED0_ON_L = 0x06
_N_CH = 16


def us_to_duty16(us) -> int:
    period_us = 1_000_000.0 / PWM_FREQ_HZ
    duty = int(round(float(us) / period_us * 65535))
    return max(0, min(65535, duty))


def duty16_to_us(duty) -> float:
    return float(duty) / 65535.0 * (1_000_000.0 / PWM_FREQ_HZ)


class Pca9685:

    def __init__(self, force_sim=False):
        self._pca = None
        self.mode = "SIM"
        self.error = None
        self.log = None
        self.freq_ok = True
        self.resets = 0
        self.i2c_errors = 0
        self.mismatches = 0
        self.last_mismatch = None
        self.gave_up = False
        self._bad_beats = 0
        self._recoveries = []
        self._frame = bytearray(1 + 4 * _N_CH)
        self._frame[0] = _LED0_ON_L
        self._dirty = False
        self._last = {}

        if force_sim:
            self.error = "forced"
            print("[pca] SIM mode (forced)")
            return
        try:
            import board
            import busio
            from adafruit_pca9685 import PCA9685
            i2c = busio.I2C(board.SCL, board.SDA)
            pca = PCA9685(i2c, address=I2C_ADDRESS)
            self._pca = pca
            try:
                self._wake()
            except Exception as e:
                print("[pca] could not wake the chip directly (%s) - the health check "
                      "will do it" % e.__class__.__name__)
                self._pca.frequency = PWM_FREQ_HZ
            self.mode = "HW"
            print("[pca] PCA9685 at 0x%02X -> HARDWARE mode" % I2C_ADDRESS)
        except Exception as e:
            self.error = "%s: %s" % (e.__class__.__name__, e)
            print("[pca] no PCA9685 (%s) -> SIMULATION mode" % e.__class__.__name__)

    def _wake(self):
        self._pca.mode1_reg = 0x00
        time.sleep(0.001)
        self._pca.frequency = PWM_FREQ_HZ

    def set_duty(self, ch, duty):
        duty = int(duty)
        if duty == 0xFFFF:
            on, off = 0x1000, 0
        else:
            on, off = 0, (duty + 1) >> 4
        i = 1 + 4 * int(ch)
        self._frame[i] = on & 0xFF
        self._frame[i + 1] = (on >> 8) & 0xFF
        self._frame[i + 2] = off & 0xFF
        self._frame[i + 3] = (off >> 8) & 0xFF
        self._dirty = True
        self._last[int(ch)] = duty

    def staged(self, ch):
        return self._last.get(int(ch))

    def flush(self):
        if self._pca is None or not self._dirty:
            self._dirty = False
            return
        dev = getattr(self._pca, "i2c_device", None)
        if dev is None:
            for ch, duty in self._last.items():
                self._pca.channels[ch].duty_cycle = duty
            self._dirty = False
            return
        with dev:
            dev.write(self._frame)
        self._dirty = False

    def read_duty(self, ch):
        if self._pca is None:
            return None
        try:
            duty = int(self._pca.channels[int(ch)].duty_cycle)
        except Exception as e:
            self.note_error(e)
            return None
        if (duty >> 4) & 0xE000:
            self.i2c_errors += 1
            self.error = ("read of ch%d came back 0x%X - reserved bits set, so the "
                          "bus is not being acknowledged" % (int(ch), duty))
            self._log("err", "i2c_garbage", ch=int(ch), duty=duty, n=self.i2c_errors)
            return None
        return duty

    def verify(self, ch, want):
        got = self.read_duty(ch)
        if got is None:
            return True
        want = int(want)
        if abs(got - want) <= PCA_DUTY_TOLERANCE:
            return True
        self.mismatches += 1
        self.last_mismatch = ("ch%d: the chip is holding %.0fus, the table says %.0fus"
                              % (int(ch), duty16_to_us(got), duty16_to_us(want)))
        self._log("err", "chip_disagrees", ch=int(ch), chip_duty=got,
                  table_duty=want, chip_us=round(duty16_to_us(got)),
                  table_us=round(duty16_to_us(want)), n=self.mismatches)
        self._last.pop(int(ch), None)
        self.set_duty(ch, want)
        try:
            self.flush()
        except Exception as e:
            self.note_error(e)
        return False

    def _config_bad(self):
        if self._pca is None:
            return None
        try:
            mode1 = int(self._pca.mode1_reg)
            prescale = int(self._pca.prescale_reg)
        except Exception:
            return None
        ref = float(getattr(self._pca, "reference_clock_speed", 25000000))
        want = int(ref / 4096.0 / float(PWM_FREQ_HZ) + 0.5) - 1
        return bool(mode1 & 0x10) or prescale != want

    def _config_bad_confirmed(self):
        for i in range(PCA_RESET_CONFIRM):
            if i:
                time.sleep(PCA_CONFIRM_GAP_S)
            if self._config_bad() is not True:
                return False
        return True

    def health_check(self):
        if self._pca is None or self.gave_up:
            return
        bad = self._config_bad()
        if bad is None:
            return
        if not bad:
            self._bad_beats = 0
            if not self.freq_ok:
                self.freq_ok = True
                print("[pca] back at %dHz - outputs re-armed." % PWM_FREQ_HZ)
            return

        self._bad_beats += 1
        if self.freq_ok and self._bad_beats >= PCA_FREQ_BAD_BEATS:
            self.freq_ok = False
            print("[pca] NOT running at %dHz (%d bad reads). Every output is held at "
                  "ZERO until it is - at the wrong prescale the pulses come out the "
                  "wrong WIDTH, which puts every joint past its limits at once."
                  % (PWM_FREQ_HZ, self._bad_beats))
        if not self._config_bad_confirmed():
            return
        self._repair()

    def _repair(self):
        now = time.monotonic()
        self._recoveries = [t for t in self._recoveries if now - t < PCA_STORM_WINDOW_S]
        if len(self._recoveries) > PCA_STORM_N:
            self.gave_up = True
            self.freq_ok = False
            self._log("err", "pca_gave_up", resets=self.resets,
                      window_s=PCA_STORM_WINDOW_S)
            print("[pca] the driver has been found reset %d times in %.0fs. GIVING UP: "
                  "every output is now dead and stays dead. This is a POWER fault - "
                  "the supply cannot hold twelve servos. Fix the supply and restart."
                  % (len(self._recoveries), PCA_STORM_WINDOW_S))
            return
        self._recoveries.append(now)
        self.resets += 1
        try:
            self._wake()
            self._last.clear()
            self._log("err", "pca_reset", resets=self.resets)
            print("[pca] the driver had been reset - frequency re-applied (%d so far)."
                  % self.resets)
        except Exception as e:
            self.note_error(e)

    def note_error(self, exc):
        self.i2c_errors += 1
        self.error = "%s: %s" % (exc.__class__.__name__, exc)
        self._log("err", "i2c", why=self.error, n=self.i2c_errors)

    def _log(self, level, kind, **f):
        if self.log is not None:
            self.log.event(level, kind, **f)

    @property
    def drivable(self) -> bool:
        return self.freq_ok and not self.gave_up

    def status(self):
        return {"mode": self.mode, "freq_ok": bool(self.freq_ok),
                "gave_up": bool(self.gave_up), "resets": int(self.resets),
                "i2c_errors": int(self.i2c_errors), "mismatches": int(self.mismatches),
                "last_mismatch": self.last_mismatch, "error": self.error}

    def shutdown(self):
        for ch in range(_N_CH):
            self.set_duty(ch, 0)
        try:
            self.flush()
        except Exception:
            pass
