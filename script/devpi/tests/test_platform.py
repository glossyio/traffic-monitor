"""The Pi itself: model, OS, power, storage, and temperature."""

MIN_FREE_BYTES = 2 * 1024**3
MAX_SOC_MILLIDEGREES = 80_000


def test_raspberry_pi_5(host):
    model = host.file("/proc/device-tree/model").content_string.rstrip("\x00")
    assert "Raspberry Pi 5" in model, f"model is {model!r}"


def test_64_bit_os(host):
    architecture = host.check_output("dpkg --print-architecture")
    assert architecture == "arm64", f"architecture is {architecture}"


def test_not_throttled(host):
    with host.sudo():
        throttled = host.check_output("vcgencmd get_throttled")
    # Bits 0-3: under-voltage, frequency capped, throttled, soft temperature limit, now;
    # bits 16-19: the same, at some point since boot.
    assert throttled == "throttled=0x0", f"{throttled}; check the power supply and cooling"


def test_root_free_space(host):
    free = int(host.check_output("df --output=avail -B1 / | tail -n 1"))
    assert free >= MIN_FREE_BYTES, f"{free / 1024**3:.1f} GiB free on /"


def test_soc_temperature(host):
    temperature = int(host.file("/sys/class/thermal/thermal_zone0/temp").content_string)
    assert temperature < MAX_SOC_MILLIDEGREES, f"SoC at {temperature / 1000:.1f} °C"
