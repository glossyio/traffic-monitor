##################
# Adapted from https://github.com/SkatterBencher/rpi5-telemetry-python,
# with additional ideas from https://www.tomshardware.com/how-to/raspberry-pi-benchmark-vcgencmd
#
# To run `python3 utils\rpi5-nodered-telemetry.py` after cd'ing to your traffic-monitor location.
#
# Output is printed in JSON format, with keys named after the various vcgencmd options.
#
# Adapted by MHL, September 2024.
###################

import csv
import os
import psutil
import time
import fcntl
import struct
import json
import subprocess
import sys

class Measure:
    def __init__(self, command, value=""):
        self.command = command
        self.value = value

class Message:
    __format_string = '6I1028s'
    def __init__(self):
        self.header = [0] * 6
        self.byte_array = bytearray(1028)

    def pack(self):
        return struct.pack(self.__format_string, *self.header, self.byte_array)

    def unpack(self, data):
        unpacked_data = struct.unpack(self.__format_string, data)
        self.header = unpacked_data[:6]
        self.byte_array = unpacked_data[6]

    def get_size(self):
        return struct.calcsize(self.__format_string)

def get_vcgencmd_output(file_desc, command):
    GET_GENCMD_RESULT = 0x00030080
    MAX_STRING = 1024

    p = Message()
    len_cmd = len(command)
    assert len_cmd < MAX_STRING, "vcgencmd command too long"
    p.header[0] = p.get_size()
    p.header[2] = GET_GENCMD_RESULT
    p.header[3] = MAX_STRING
    p.byte_array[:len_cmd] = map(ord, command)
    byte_data = bytearray(p.pack())
    ret_val = fcntl.ioctl(file_desc, 0xC0086400, byte_data)
    if ret_val < 0:
        print(f"ioctl_set_msg failed: {ret_val}")
        return -1
    p.unpack(byte_data)
    return p.byte_array.decode("utf8").rstrip('\x00')

def get_cpu_usage():
    # Retrieve and return the CPU usage percentage per core
    return psutil.cpu_percent(interval=1, percpu=True)

def decode_readmr_4(value):
    meanings = {
        "000": "SDRAM low temperature operating limit exceeded",
        "001": "4x refresh",
        "010": "2x refresh",
        "011": "1x refresh (default)",
        "100": "0.5x refresh",
        "101": "0.25x refresh, no derating",
        "110": "0.25x refresh, with derating",
        "111": "SDRAM high temperature operating limit exceeded",
    }
    binary_string = f"{value:03b}" # convert integer in 3-bit binary string
    return meanings.get(binary_string, "Meaning")

def decode_throttling(throttle_hex_value):

    error_messages = {
      0: "UV",
      1: "ArmFreqCap",
      2: "CurThrottle",
      3: "SoftTempLimit",
      16: "UV_occured",
      17: "ArmFreqCap_occured",
      18: "Throttle_occured",
      19: "SoftTempLimit_occured",
    }
    try:
        # Convert hex value to binary string (remove leading '0b')
        binary_value = bin(int(throttle_hex_value, 16))[2:]
    except ValueError:
        return [("Invalid hex value", "N/A")]

    # Invert binary string (active bits are 1s)
    binary_value = binary_value[::-1]

    # Pad binary string with leading zeros to ensure consistent length
    binary_value = binary_value.zfill(20)

    # Initialize empty dictionary for results
    results = {}
    for i, message in error_messages.items():
        # Check if index is within binary string length (avoid out-of-range access)
        if i < len(binary_value):
            results[message] = "Yes" if binary_value[i] == "1" else "No"
        else:
            results[message] = "No (bit out of range)"  # Indicate missing bit

    return results

def pmic_read_adc(mb):
    # Run the command and capture the output
    output = get_vcgencmd_output(mb, 'pmic_read_adc')
    # Decode byte output to string and split by spaces
    parts = output.strip().split()
    return [(parts[i], parts[i + 1]) for i in range(0, len(parts), 2)]

# Decode the results of "get_config"
def decode_config(config_values):
    config = {}
    for config_value in config_values.split('\n'):
        # distinguish between two formats, based on whether the config_value
        # contains a colon
        if ":" in config_value:
            # example: hdmi_force_cec_address:0=65535
            # example: hdmi_force_cec_address:1=65535
            # these are mapped to:
            # hdmi_force_cec_address: {0:65535, 1: 65535}
            parts = config_value.split(':')
            label = parts[0]
            value_parts = parts[1].split('=')
            index = value_parts[0]
            value = int(value_parts[1])
            if label in config:
                config[label][index] = value
            else:
                config[label] = {}
                config[label][index] = value
        else:
            # example: arm_64bit=1 is mapped to: arm_64bit:1
            # but if the string after the equal sign is not numeric
            # then it is kept as a string
            # for example, init_uart_clock=0x2dc6c00 is mapped to init_uart_clock: "0x2dc6c00"
            config_components = config_value.split('=')
            label = config_components[0]
            value = config_components[1]
            # convert numeric (including negative) string to int
            try:
                final_value = int(value)
            except:
                final_value = value
            config[label] = final_value
    return config

def main():
    try:
        mb = os.open("/dev/vcio", os.O_RDWR)
    except OSError as e:
        print(f"Can't open device file you need to run this script as root. Error: {e}")
        exit(-1)
       
    fieldnames = [
        "timestamp",
        "cpu_percent",
        "arm_mhz",
        "core_mhz",
        "h264_mhz",
        "isp_mhz",
        "v3d_mhz",
        "uart_mhz",
        "pwm_mhz",
        "emmc_mhz",
        "pixel_mhz",
        "vec_mhz",
        "hdmi_mhz",
        "dpi_mhz",
        "arm_temp",
        "core_volt",
        "sdram_c_volt",
        "sdram_i_volt",
        "sdram_p_volt",
        "3V7_WL_SW_A",
        "3V3_SYS_A",
        "1V8_SYS_A",
        "DDR_VDD2_A",
        "DDR_VDDQ_A",
        "1V1_SYS_A",
        "0V8_SW_A",
        "VDD_CORE_A",
        "3V3_DAC_A",
        "3V3_ADC_A",
        "0V8_AON_A",
        "HDMI_A",
        "3V7_WL_SW_V",
        "3V3_SYS_V",
        "1V8_SYS_V",
        "DDR_VDD2_V",
        "DDR_VDDQ_V",
        "1V1_SYS_V",
        "0V8_SW_V",
        "VDD_CORE_V",
        "3V3_DAC_V",
        "3V3_ADC_V",
        "0V8_AON_V",
        "HDMI_V",
        "EXT5V_V",
        "BATT_V",
        "readmr_4",
        "readmr_5",
        "readmr_6",
        "readmr_8",
        "throttle_hex",
        "UV",
        "ArmFreqCap",
        "CurThrottle",
        "SoftTempLimit",
        "UV_occured",
        "ArmFreqCap_occured",
        "Throttle_occured",
        "SoftTempLimit_occured",
    ]

    clocks = {
        "arm": Measure("measure_clock arm"),
        "core": Measure("measure_clock core"),
        "h264": Measure("measure_clock h264"),
        "isp": Measure("measure_clock isp"),
        "v3d": Measure("measure_clock v3d"),
        "uart": Measure("measure_clock uart"),
        "pwm": Measure("measure_clock pwm"),
        "emmc": Measure("measure_clock emmc"),
        "pixel": Measure("measure_clock pixel"),
        "vec": Measure("measure_clock vec"),
        "hdmi": Measure("measure_clock hdmi"),
        "dpi": Measure("measure_clock dpi"),
    }

    volts = {
        "core": Measure("measure_volts core"),
        "sdram_c": Measure("measure_volts sdram_c"),
        "sdram_i": Measure("measure_volts sdram_i"),
        "sdram_p": Measure("measure_volts sdram_p"),
    }
    
    mr = {
        "readmr_4": Measure("readmr 4"),
        "readmr_5": Measure("readmr 5"),
        "readmr_6": Measure("readmr 6"),
        "readmr_8": Measure("readmr 8"),
    }


    # Get status information
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    fw_version = get_vcgencmd_output(mb, "version")

    # Get processor usage information
    cpu_percent = psutil.cpu_percent(interval=1)

    # Get Vcgencmd metrics
    measure_clock = {}
    for key, command in clocks.items():
        value = get_vcgencmd_output(mb, command.command).split('=')[1]
        measure_clock[key] = value

    arm_temp = get_vcgencmd_output(mb, "measure_temp").split('=')[1]

    measure_volts = {}
    for key, command in volts.items():
        value = get_vcgencmd_output(mb, command.command).split('=')[1]
        measure_volts[key] = value

    read_mr = {}    
    for key, command in mr.items():
        value = get_vcgencmd_output(mb, command.command).split(':')[5]
        read_mr[key] = value

    # Check for throttling
    throttle_hex_value = get_vcgencmd_output(mb, "get_throttled").split('=')[1]
    throttle_status = decode_throttling(throttle_hex_value)

    # Measure PMIC telemetry
    adc_values = pmic_read_adc(mb)
    pmic_read_values = {}
    for label, value in adc_values:
        pmic_read_values[label] = value

    # Get system configuration
    config = decode_config(get_vcgencmd_output(mb, "get_config int"))

    # Get memory splits
    memory_split_arm = get_vcgencmd_output(mb, "get_mem arm").split('=')[1]
    memory_split_gpu = get_vcgencmd_output(mb, "get_mem gpu").split('=')[1]

    # Get memory stats from /proc/meminfo
    meminfo_result = subprocess.run(["cat", "/proc/meminfo"], text=True, stdout=subprocess.PIPE)
    meminfo_values = meminfo_result.stdout.split('\n')
    meminfo = {}
    for meminfo_value in meminfo_values:
        meminfo_parts = meminfo_value.split(':')
        if len(meminfo_parts) > 1:
            label = meminfo_parts[0]
            value = meminfo_parts[1].strip()
            meminfo[label] = value

    result = {
        "timestamp": timestamp,
        "version": fw_version,
        "cpu_percent": cpu_percent,
        "measure_clock": measure_clock,
        "arm_temp": arm_temp,
        "measure_volts": measure_volts,
        "read_mr": read_mr,
        "throttle_hex": throttle_hex_value,
        "throttle_status": throttle_status,
        "pmic_read_adc": pmic_read_values,
        "config": config,
        "memory_split_arm": memory_split_arm,
        "memory_split_gpu": memory_split_gpu,
        "meminfo": meminfo
    }

    print(json.dumps(result))



if __name__ == "__main__":
    main()