"""ROS-free ADC driver package surface (D-73)."""

from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_package_declares_rclcpp_and_sensor_msgs():
    package = ET.parse(ROOT / "package.xml").getroot()
    name = package.find("name")
    assert name is not None and name.text == "sensor_adc"
    dependencies = {
        element.text
        for element in package.findall("depend")
        if element.text
    }
    assert {"rclcpp", "sensor_msgs", "std_msgs"} <= dependencies


def test_node_source_exists():
    source = ROOT / "src" / "main_node.cpp"
    assert source.is_file()
    text = source.read_text(encoding="utf-8")
    assert "rclcpp" in text


def _source() -> str:
    return (ROOT / "src" / "main_node.cpp").read_text(encoding="utf-8")


def test_i2c_returns_are_checked_and_failures_skip_publishing():
    """A bus fault must publish nothing, not zeros (fail-closed, imu pattern).

    The CORE evidence gate judges freshness by the arrival of samples; a node
    that keeps publishing zeroed ADC values through a dead bus defeats it.
    """
    text = _source()
    assert "= wiringPiI2CRawWrite" in text, "write return code must be captured"
    assert "= wiringPiI2CRawRead" in text, "read return code must be captured"
    assert "written < 1" in text
    assert "got != 2" in text
    assert "read_cycle" in text
    assert "consecutive_failures_" in text


def test_health_topic_is_latched():
    text = _source()
    assert "sensors/adc/status" in text
    assert "transient_local" in text


def test_init_failure_exits_instead_of_asserting():
    text = _source()
    assert "assert(" not in text, (
        "assert(false) compiles out under NDEBUG; init failure must exit")
    assert "throw std::runtime_error" in text


def test_every_bus_transaction_holds_the_shared_i2c_lock():
    # D-192 review: rosylib.Battery and control's ir_adc_node take an exclusive
    # flock on their /dev/i2c-1 descriptor per transaction; so does this node.
    text = _source()
    assert "#include <sys/file.h>" in text
    wrapper = text[text.index("bool read_channel(int channel"):text.index("bool read_channel_locked(")]
    assert wrapper.index("flock(fd_, LOCK_EX)") < wrapper.index("read_channel_locked(channel, value)")
    assert wrapper.index("read_channel_locked(channel, value)") < wrapper.index("flock(fd_, LOCK_UN)")
    locked = text[text.index("bool read_channel_locked("):text.index("bool read_cycle(")]
    for step in ("wiringPiI2CRawWrite", "sleep_for", "wiringPiI2CRawRead"):
        assert step in locked, step
    assert "flock" not in locked  # one lock, taken once, released on every path
