"""
传感器模块 - 读取各类传感器数据
"""

import machine
import time
from machine import ADC, Pin, UART
import config


# ============ 全局传感器对象 ============
_soil_adc = None
_co2_uart = None
_dht22_sensor = None
_dip_pins = None


def init():
    """初始化所有传感器"""
    global _soil_adc, _co2_uart, _dip_pins, _dht22_sensor
    
    # 土壤湿度 ADC
    _soil_adc = ADC(Pin(config.SOIL_ADC_PIN))
    _soil_adc.atten(ADC.ATTN_11DB)  # 配置为 0-3.3V 量程
    
    # CO2 传感器 UART
    _co2_uart = UART(
        config.CO2_UART_NUM,
        baudrate=config.CO2_UART_BAUD,
        tx=Pin(config.CO2_UART_TX),
        rx=Pin(config.CO2_UART_RX)
    )
    
    # DHT22 温湿度传感器
    try:
        import dht
        _dht22_sensor = dht.DHT22(Pin(config.DHT22_PIN))
        print("[传感器] DHT22 初始化成功")
    except Exception as e:
        print(f"[传感器] DHT22 初始化失败: {e}")
        _dht22_sensor = None
    
    # 拨码开关引脚
    _dip_pins = [Pin(pin, Pin.IN, Pin.PULL_UP) for pin in config.DIP_SWITCH_PINS]
    
    print("[传感器] 初始化完成")
    return True


def read_soil_moisture():
    """
    读取土壤湿度
    返回: 湿度百分比 (0-100)
    说明: 干土≈4095, 湿土≈1500
    """
    try:
        # 读取多次取平均
        samples = []
        for _ in range(5):
            raw = _soil_adc.read()
            samples.append(raw)
            time.sleep_ms(10)
        
        raw_avg = sum(samples) / len(samples)
        
        # 转换为百分比
        # raw = 4095 时 = 0% (干土)
        # raw = 1500 时 = 100% (湿土)
        moisture = int((config.SOIL_ADC_MAX - raw_avg) / (config.SOIL_ADC_MAX - config.SOIL_ADC_MIN) * 100)
        moisture = max(0, min(100, moisture))  # 限制范围
        
        return moisture
        
    except Exception as e:
        print("[传感器] 土壤读取失败:", e)
        return None  # 传感器故障，返回 None 让主循环触发告警


def read_co2():
    """
    读取 CO2 浓度
    返回: CO2 浓度 (ppm)
    说明: MH-Z19B 红外 CO2 传感器
    """
    try:
        # 发送读取命令（MH-Z19B 标准读取浓度命令）
        # 格式: 0xFF, 0x01, 0x86, 0x00×6, checksum
        # 校验和 = (~(0xFF + 0x01 + 0x86)) & 0xFF = 0x79
        cmd = bytearray([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])
        _co2_uart.write(cmd)
        
        # 等待响应
        time.sleep_ms(100)
        
        if _co2_uart.any() >= 9:
            data = _co2_uart.read(9)
            if data and len(data) >= 9:
                # 校验：字节 0 应为 0xFF，字节 1 应为 0x86
                if data[0] == 0xFF and data[1] == 0x86:
                    co2 = (data[2] << 8) + data[3]
                    return co2
        
        # 如果读取失败，返回 None 让主循环触发告警
        return None
        
    except Exception as e:
        print("[传感器] CO2读取失败:", e)
        return None  # 传感器故障，返回 None 让主循环触发告警


def read_dht22():
    """
    读取 DHT22 温湿度传感器
    返回: (温度°C, 湿度%)
    """
    try:
        if _dht22_sensor is None:
            print("[传感器] DHT22 未初始化")
            return (None, None)
        
        _dht22_sensor.measure()
        temp = _dht22_sensor.temperature()
        hum = _dht22_sensor.humidity()
        
        return (temp, hum)
        
    except Exception as e:
        # DHT22 不可用，返回 None 让主循环触发告警
        print("[传感器] DHT22读取失败:", e)
        return (None, None)


def read_plant_type():
    """
    读取3位拨码开关，获取植物类型
    支持编码 0-7，对应 8 种植物
    返回: 植物名称字符串
    """
    try:
        values = [pin.value() for pin in _dip_pins]
        # PULL_UP 输入取反: OFF(断开)→1→取反为0, ON(接地)→0→取反为1
        bits = [1 - v for v in values]
        # DIP_SWITCH_PINS = [13, 12, 14]  (3位，支持8种植物)
        # 编码规则: bits[0]=bit0(DIP1), bits[1]=bit1(DIP2), bits[2]=bit2(DIP3)
        index = (bits[2] << 2) | (bits[1] << 1) | bits[0]
        
        plant = config.get_plant_name(index)
        return plant
        
    except Exception as e:
        print("[传感器] 拨码读取失败:", e)
        return config.get_plant_name(0)  # 默认返回生菜（拨码0）


def read_all():
    """
    读取所有传感器数据
    返回: 字典包含所有传感器值
    """
    soil = read_soil_moisture()
    co2 = read_co2()
    temp, hum = read_dht22()
    plant = read_plant_type()
    
    return {
        "soil_moisture": soil,
        "co2_ppm": co2,
        "temperature": temp,
        "humidity": hum,
        "plant_type": plant,
        "timestamp": time.time()
    }


def calibrate_soil():
    """
    土壤传感器校准
    提示用户将传感器放入干土和湿土中测量
    """
    print("=== 土壤传感器校准 ===")
    print("将传感器放入干土中，等待5秒...")
    time.sleep(5)
    
    dry_samples = []
    for i in range(10):
        dry_samples.append(_soil_adc.read())
        time.sleep(0.5)
    dry_avg = sum(dry_samples) / len(dry_samples)
    print(f"干土 ADC 平均值: {dry_avg}")
    
    print("将传感器放入湿土中，等待5秒...")
    time.sleep(5)
    
    wet_samples = []
    for i in range(10):
        wet_samples.append(_soil_adc.read())
        time.sleep(0.5)
    wet_avg = sum(wet_samples) / len(wet_samples)
    print(f"湿土 ADC 平均值: {wet_avg}")
    
    print(f"\n校准结果:")
    print(f"  SOIL_ADC_MAX (干土) = {int(dry_avg)}")
    print(f"  SOIL_ADC_MIN (湿土) = {int(wet_avg)}")
    print("请将上述值更新到 config.py 中")


def test_all():
    """测试所有传感器"""
    print("=== 传感器测试 ===")
    
    print("\n[1/4] 测试土壤湿度...")
    for i in range(3):
        soil = read_soil_moisture()
        print(f"  土壤湿度: {soil}%")
        time.sleep(0.5)
    
    print("\n[2/4] 测试CO2...")
    for i in range(3):
        co2 = read_co2()
        print(f"  CO2浓度: {co2}ppm")
        time.sleep(0.5)
    
    print("\n[3/4] 测试温湿度...")
    temp, hum = read_dht22()
    print(f"  温度: {temp}C, 湿度: {hum}%")
    
    print("\n[4/4] 测试拨码开关...")
    plant = read_plant_type()
    print(f"  当前植物: {plant}")
    
    print("\n=== 测试完成 ===")
