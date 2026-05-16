"""
传感器模块 - 读取各类传感器数据
"""

import machine
import time
from machine import ADC, Pin
import config


# ============ 全局传感器对象 ============
_soil_adc = None
_soil_pin = None
_dht_sensor = None
_dip_pins = None


def init():
    """初始化所有传感器"""
    global _soil_adc, _soil_pin, _dip_pins, _dht_sensor
    
    # 土壤湿度传感器：支持模拟量 ADC 和比较器数字量两种模块
    if getattr(config, "SOIL_SENSOR_MODE", "adc") == "digital":
        _soil_pin = Pin(config.SOIL_ADC_PIN, Pin.IN)
        _soil_adc = None
        print(f"[Sensor] Soil digital input initialized on GPIO{config.SOIL_ADC_PIN}")
    else:
        _soil_adc = ADC(Pin(config.SOIL_ADC_PIN))
        _soil_adc.atten(ADC.ATTN_11DB)  # 配置为 0-3.3V 量程
        _soil_pin = None
        print(f"[Sensor] Soil ADC initialized on GPIO{config.SOIL_ADC_PIN}")
    
    # 温湿度传感器
    try:
        import dht
        if config.DHT_TYPE == "DHT22":
            _dht_sensor = dht.DHT22(machine.Pin(config.DHT_PIN))
        else:
            _dht_sensor = dht.DHT11(machine.Pin(config.DHT_PIN))
        print(f"[Sensor] {config.DHT_TYPE} initialized on GPIO{config.DHT_PIN}")
    except Exception as e:
        print(f"[Sensor] {config.DHT_TYPE} initialization failed: {e}")
        _dht_sensor = None
    
    # 拨码开关引脚
    _dip_pins = [Pin(pin, Pin.IN, Pin.PULL_UP) for pin in config.DIP_SWITCH_PINS]
    
    print("[Sensor] Initialization complete")
    return True


def read_soil_moisture():
    """
    读取土壤湿度
    返回: 湿度百分比 (0-100)
    说明: 干土≈4095, 湿土≈1500
    """
    try:
        if getattr(config, "SOIL_SENSOR_MODE", "adc") == "digital":
            raw = _soil_pin.value()
            dry_value = getattr(config, "SOIL_DIGITAL_DRY_VALUE", 1)
            return 0 if raw == dry_value else 100

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
        print("[Sensor] Soil read failed:", e)
        return None  # 传感器故障，返回 None 让主循环触发告警


def read_dht22():
    """
    读取温湿度传感器
    返回: (温度°C, 湿度%)
    DHT11/DHT22 偶尔读取失败属于正常现象，增加重试机制
    """
    if _dht_sensor is None:
        print("[Sensor] DHT not initialized")
        return (None, None)

    for attempt in range(3):
        try:
            _dht_sensor.measure()
            temp = _dht_sensor.temperature()
            hum = _dht_sensor.humidity()
            print(f"[Sensor] DHT OK: T={temp}C H={hum}%")
            return (temp, hum)
        except OSError as e:
            print(f"[Sensor] DHT read failed (attempt {attempt + 1}/3): {e}")
            time.sleep_ms(800)  # 延长等待，DHT11 需要至少 1s 间隔

    print("[Sensor] DHT all attempts failed")
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
        print("[Sensor] DIP switch read failed:", e)
        return config.get_plant_name(0)  # 默认返回生菜（拨码0）


def read_all():
    """
    读取所有传感器数据
    返回: 字典包含所有传感器值
    """
    soil = read_soil_moisture()
    temp, hum = read_dht22()
    plant = read_plant_type()
    
    return {
        "soil_moisture": soil,
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
    print("=== Soil Sensor Calibration ===")
    print("Place sensor in dry soil, wait 5s...")
    time.sleep(5)
    
    dry_samples = []
    for i in range(10):
        dry_samples.append(_soil_adc.read())
        time.sleep(0.5)
    dry_avg = sum(dry_samples) / len(dry_samples)
    print(f"Dry soil ADC average: {dry_avg}")
    
    print("Place sensor in wet soil, wait 5s...")
    time.sleep(5)
    
    wet_samples = []
    for i in range(10):
        wet_samples.append(_soil_adc.read())
        time.sleep(0.5)
    wet_avg = sum(wet_samples) / len(wet_samples)
    print(f"Wet soil ADC average: {wet_avg}")
    
    print(f"\nCalibration results:")
    print(f"  SOIL_ADC_MAX (Dry soil) = {int(dry_avg)}")
    print(f"  SOIL_ADC_MIN (Wet soil) = {int(wet_avg)}")
    print("Please update these values in config.py")


def test_all():
    """测试所有传感器"""
    print("=== Sensor Test ===")
    
    print("\n[1/3] Testing soil moisture...")
    for i in range(3):
        soil = read_soil_moisture()
        print(f"  Soil moisture: {soil}%")
        time.sleep(0.5)
    
    print("\n[2/3] Testing temp & humidity...")
    temp, hum = read_dht22()
    print(f"  Temp: {temp}C, Hum: {hum}%")
    
    print("\n[3/3] Testing DIP switch...")
    plant = read_plant_type()
    print(f"  Current plant: {plant}")
    
    print("\n=== Test Complete ===")
