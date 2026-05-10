import socket
import time
import math

UDP_IP = "192.168.4.1" # ESP32 SoftAP IP
UDP_PORT = 4210

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print("50Hz 동적 스로틀 스윕 테스트를 시작합니다... (종료: Ctrl+C)")

counter = 0
try:
    while True:
        # 사인 파형을 이용해 스로틀 값을 1000 ~ 1500 사이로 부드럽게 변화시킴
        throttle_val = int(1250 + 250 * math.sin(counter * 0.1))
        
        # 데이터 포맷: Roll, Pitch, Throttle, Yaw, AUX1(Arm), AUX2, 3, 4
        message = f"1500,1500,{throttle_val},1500,1000,1000,1000,1000"
        
        sock.sendto(message.encode('ascii'), (UDP_IP, UDP_PORT))
        counter += 1
        time.sleep(0.02) # 50Hz
except KeyboardInterrupt:
    print("\n테스트가 종료되었습니다.")