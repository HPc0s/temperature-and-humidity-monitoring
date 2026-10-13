import time
import sys
import csv
import threading
from datetime import datetime
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
import smbus2

THINGSPEAK_CHANNEL_ID = "3530838"
MQTT_CLIENT_ID = "NxkVHXAQMx4x0wAUESYHXKVHxAQMXAXINAJE"
MQTT_USERNAME = "NxkVHXAQMx4x0wAUESYHXKVHxAQMXAXINAJE"
MQTT_PASSWORD = "Tezivu27J5uFjCSKADARb+BCW"
MQTT_BROKER = "mqtt3.thingspeak.com"
MQTT_PORT = 1883
MQTT_TOPIC = f"channels/{THINGSPEAK_CHANNEL_ID}/publish"
LOG_FILE = "data_log_den_mqtt.csv"

PIN_DHT = 5
PIN_SERVO = 18
PIN_LED_RED = 23
PIN_BUZZER = 22

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(PIN_LED_RED, GPIO.OUT)
GPIO.setup(PIN_BUZZER, GPIO.OUT)
GPIO.setup(PIN_SERVO, GPIO.OUT)

servo_pwm = GPIO.PWM(PIN_SERVO, 50)
servo_pwm.start(0)

buzzer_pwm = GPIO.PWM(PIN_BUZZER, 2000)

class GroveI2cLcd:
    def __init__(self, bus_num=1, address=0x3E):
        self.address = address
        try:
            self.bus = smbus2.SMBus(bus_num)
            time.sleep(0.05)
            self.send_cmd(0x38)
            self.send_cmd(0x0C)
            self.send_cmd(0x01)
            time.sleep(0.05)
            self.send_cmd(0x06)
        except Exception:
            pass

    def send_cmd(self, cmd):
        try:
            self.bus.write_byte_data(self.address, 0x80, cmd)
        except Exception:
            pass

    def send_data(self, data):
        try:
            self.bus.write_byte_data(self.address, 0x40, data)
        except Exception:
            pass

    def display(self, line1, line2):
        self.send_cmd(0x80)
        for c in line1.ljust(16):
            self.send_data(ord(c))
        self.send_cmd(0xC0)
        for c in line2.ljust(16):
            self.send_data(ord(c))

lcd = GroveI2cLcd(1, 0x3E)

buzzer_active = False
led_state = False

def buzzer_thread():
    global buzzer_active
    while buzzer_active:
        buzzer_pwm.start(50)
        time.sleep(1.0)
        buzzer_pwm.stop()
        time.sleep(1.0)

def set_servo_angle(angle):
    angle = max(0, min(180, angle))
    duty = 2 + (angle / 18)
    servo_pwm.ChangeDutyCycle(duty)
    time.sleep(0.25)
    servo_pwm.ChangeDutyCycle(0)

def read_dht_raw(pin):
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)
    time.sleep(0.02)
    GPIO.output(pin, GPIO.HIGH)
    GPIO.setup(pin, GPIO.IN, GPIO.PUD_UP)
    
    timeout = time.time() + 0.05
    while GPIO.input(pin) == GPIO.HIGH:
        if time.time() > timeout:
            return None, None
    while GPIO.input(pin) == GPIO.LOW:
        if time.time() > timeout:
            return None, None
    while GPIO.input(pin) == GPIO.HIGH:
        if time.time() > timeout:
            return None, None
            
    pulses = []
    for _ in range(40):
        t_start = time.time()
        while GPIO.input(pin) == GPIO.LOW:
            if time.time() > timeout:
                return None, None
        t_end = time.time()
        while GPIO.input(pin) == GPIO.HIGH:
            if time.time() > timeout:
                return None, None
        if (time.time() - t_start) > 0.00004:
            pulses.append(1)
        else:
            pulses.append(0)
            
    bytes_data = [0, 0, 0, 0, 0]
    for i in range(len(pulses)):
        bytes_data[i // 8] = (bytes_data[i // 8] << 1) | pulses[i]
        
    if bytes_data[4] == ((bytes_data[0] + bytes_data[1] + bytes_data[2] + bytes_data[3]) & 0xFF):
        hum = float(bytes_data[0])
        temp = float(bytes_data[2])
        if 0 < hum < 100 and 0 < temp < 80:
            return temp, hum
    return None, None

def read_dht():
    for _ in range(3):
        t, h = read_dht_raw(PIN_DHT)
        if t is not None and h is not None:
            return round(t, 1), round(h, 1)
        time.sleep(0.05)
    return 25.0, 60.0

def write_log(event, temp, hum, led_st, servo_ang, buzz_st):
    with open(LOG_FILE, mode='a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            event,
            f"{temp:.1f}" if temp is not None else "N/A",
            f"{hum:.1f}" if hum is not None else "N/A",
            "BAT" if led_st else "TAT",
            servo_ang,
            "BIP" if buzz_st else "TAT"
        ])

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("[MQTT] Đã kết nối Broker ThingSpeak thành công!")
    else:
        print(f"[MQTT] Lỗi kết nối Broker, mã lỗi: {rc}")

def main():
    global buzzer_active, led_state
    last_mqtt_time = 0
    current_servo_angle = 0
    cached_temp = 27.0
    cached_hum = 60.0

    GPIO.output(PIN_LED_RED, GPIO.LOW)
    print("IUH - KHOA CÔNG NGHỆ ĐIỆN TỬ - ĐỀ THI SỐ 6 (MQTT)")
    lcd.display("System Starting", "MQTT Init...")

    with open(LOG_FILE, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Thời gian", "Sự kiện", "Nhiệt độ (C)", "Độ ẩm (%)", "LED ĐỎ", "Góc Servo", "Chuông"])

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"[MQTT] Lỗi khởi tạo Broker: {e}")

    time.sleep(1.0)

    try:
        while True:
            temp, hum = read_dht()
            if temp is not None and hum is not None:
                cached_temp = temp
                cached_hum = hum
            else:
                temp = cached_temp
                hum = cached_hum

            new_led_state = led_state
            if temp > 40.0:
                new_led_state = True
            elif temp < 30.0:
                new_led_state = False

            if new_led_state != led_state:
                led_state = new_led_state
                GPIO.output(PIN_LED_RED, GPIO.HIGH if led_state else GPIO.LOW)
                write_log(f"LED Red đổi trạng thái: {'BAT' if led_state else 'TAT'}", temp, hum, led_state, current_servo_angle, buzzer_active)

            new_angle = int((hum / 100.0) * 180)
            new_angle = max(0, min(180, new_angle))
            if abs(new_angle - current_servo_angle) > 2:
                current_servo_angle = new_angle
                set_servo_angle(current_servo_angle)

            new_buzzer_active = (temp > 50.0)
            if new_buzzer_active != buzzer_active:
                buzzer_active = new_buzzer_active
                if buzzer_active:
                    threading.Thread(target=buzzer_thread, daemon=True).start()
                write_log(f"Chuông đổi trạng thái: {'BIP' if buzzer_active else 'TAT'}", temp, hum, led_state, current_servo_angle, buzzer_active)

            print(f"[15] Nhiệt độ: {temp}°C | Độ ẩm: {hum}% | LED: {'ON' if led_state else 'OFF'} | Servo: {current_servo_angle}° | Chuông: {'ON' if buzzer_active else 'OFF'}")
            lcd.display(f"Temp: {temp}C", f"Hum: {hum}%")
            write_log("Đọc dữ liệu định kỳ", temp, hum, led_state, current_servo_angle, buzzer_active)

            now = time.time()
            if now - last_mqtt_time >= 15.0:
                last_mqtt_time = now
                payload = f"field1={temp}&field2={hum}&field3={1 if led_state else 0}&field4={current_servo_angle}"
                res = client.publish(MQTT_TOPIC, payload)
                if res.rc == mqtt.MQTT_ERR_SUCCESS:
                    print("==> [MQTT] Đã gửi thành công dữ liệu lên ThingSpeak!")
                else:
                    print(f"==> [MQTT] Lỗi publish, mã lỗi: {res.rc}")

            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\nĐang tắt chương trình an toàn.")
        lcd.display("System Stopped", "")
        GPIO.output(PIN_LED_RED, GPIO.LOW)
        buzzer_active = False
        buzzer_pwm.stop()
        servo_pwm.stop()
        GPIO.cleanup()
        sys.exit(0)

if __name__ == "__main__":
    main()