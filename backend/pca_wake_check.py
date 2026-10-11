from config import PCA_STORM_N, PWM_FREQ_HZ
from driver import Pca9685


class FakeChip:

    def __init__(self):
        self.mode1_reg = 0x11
        self.prescale_reg = 0x1E
        self.reference_clock_speed = 25000000
        self.i2c_device = None
        self.writes = 0

    @property
    def frequency(self):
        return PWM_FREQ_HZ

    @frequency.setter
    def frequency(self, hz):
        self.writes += 1
        prescale = int(self.reference_clock_speed / 4096.0 / float(hz) + 0.5) - 1
        old_mode = self.mode1_reg
        self.mode1_reg = (old_mode & 0x7F) | 0x10
        self.prescale_reg = prescale
        self.mode1_reg = old_mode
        self.mode1_reg = old_mode | 0xA0

    @property
    def awake(self):
        return not (self.mode1_reg & 0x10)


def check():
    d = Pca9685(force_sim=True)
    chip = FakeChip()
    d._pca = chip

    chip.frequency = PWM_FREQ_HZ
    assert not chip.awake, "the fixture is wrong: this is supposed to fail to wake"
    assert d._config_bad() is True

    chip.mode1_reg = 0x11
    d._wake()
    assert chip.awake, "MODE1 = 0x%02X - still asleep" % chip.mode1_reg
    assert d._config_bad() is False, "prescale or SLEEP still wrong after _wake"

    d.freq_ok, d._bad_beats, d._recoveries, d.resets = True, 0, [], 0
    for _ in range(10):
        d.health_check()
    assert d.resets == 0, "a woken chip must not look like a reset (%d)" % d.resets
    assert d.freq_ok and not d.gave_up
    assert d._recoveries == [], d._recoveries

    chip.mode1_reg, chip.prescale_reg = 0x11, 0x1E
    for _ in range(3):
        d.health_check()
    assert chip.awake, "a reset chip must be woken"
    assert d.resets == 1, d.resets
    assert len(d._recoveries) == 1 <= PCA_STORM_N
    assert not d.gave_up, "one recovery is a glitch, not a storm"

    for _ in range(2):
        chip.mode1_reg, chip.prescale_reg = 0x11, 0x1E
        for _ in range(3):
            d.health_check()
    assert d.gave_up, "repeated resets must stop the outputs"
    assert not d.drivable

    d2 = Pca9685(force_sim=True)
    chip2 = FakeChip()
    d2._pca = chip2

    class Ch:
        def __init__(self, duty): self.duty_cycle = duty
    for garbage in (0xFFFF << 4, 0xFF00 << 4):
        chip2.channels = [Ch(garbage)]
        n0 = d2.i2c_errors
        assert d2.read_duty(0) is None, "0x%X must read as unreadable" % garbage
        assert d2.i2c_errors == n0 + 1, "a garbage read is an I2C failure"
        assert d2.verify(0, 0) is True, "unreadable must not count as a mismatch"
        assert d2.mismatches == 0, d2.mismatches

    for legal in (0, 300 << 4, 0x1000 << 4, 0xFFFF):
        chip2.channels = [Ch(legal)]
        assert d2.read_duty(0) == legal, "0x%X is a value the part can hold" % legal
    chip2.channels = [Ch(300 << 4)]
    assert d2.verify(0, 0) is False
    assert d2.mismatches == 1

    print("pca wake + garbage-read: all checks passed")


if __name__ == "__main__":
    check()
