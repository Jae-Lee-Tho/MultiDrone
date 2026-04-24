#include <WiFi.h>
#include <WiFiUdp.h>

// ==========================================
// 1. WI-FI & NETWORK SETTINGS
// ==========================================
const char* ssid = "Drone_Network";     // The ESP32 will broadcast this Wi-Fi name
const char* password = "password123";   // Must be at least 8 characters
const int udpPort = 4210;

WiFiUDP udp;
char packetBuffer[255]; // Buffer to hold incoming UDP strings

// ==========================================
// 2. DRONE CHANNELS & FAILSAFE SETTINGS
// ==========================================
// Array mapping: [0]Roll, [1]Pitch, [2]Throttle, [3]Yaw, [4]Arm(Aux1), [5]Aux2
uint16_t channels[6] = {1500, 1500, 1000, 1500, 1000, 1500};

unsigned long lastPacketTime = 0;
const unsigned long FAILSAFE_TIMEOUT_MS = 500;

unsigned long lastIbusTime = 0;
const unsigned long IBUS_INTERVAL_MS = 20; // 50Hz (Standard Betaflight refresh rate)

// ==========================================
// 3. SETUP FUNCTION (Runs once on boot)
// ==========================================
void setup() {
  // Serial0 is for USB debugging (Viewing in Arduino Serial Monitor)
  Serial.begin(115200);

  // Serial2 is for sending the IBUS protocol to the Flight Controller
  // On standard ESP32 boards, TX2 is GPIO 17
  Serial2.begin(115200, SERIAL_8N1, 16, 17);

  Serial.println("\n=========================================");
  Serial.println("  ESP32 Drone Companion Receiver Booting");
  Serial.println("=========================================");

  // Start Wi-Fi Access Point
  Serial.print("Starting Wi-Fi Access Point... ");
  WiFi.softAP(ssid, password);
  Serial.println("Done!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.softAPIP()); // Usually defaults to 192.168.4.1

  // Start UDP Listener
  udp.begin(udpPort);
  Serial.printf("Listening for Raspberry Pi UDP on Port %d\n", udpPort);
}

// ==========================================
// 4. MAIN LOOP
// ==========================================
void loop() {
  // --- A. CHECK FOR INCOMING UDP DATA ---
  int packetSize = udp.parsePacket();
  if (packetSize) {
    // Read the string (e.g., "1500,1800,1200,1500,2000")
    int len = udp.read(packetBuffer, 255);
    if (len > 0) {
      packetBuffer[len] = 0; // Null-terminate the string
    }

    // Parse the comma-separated values into our channel array
    char* token = strtok(packetBuffer, ",");
    int chIndex = 0;
    while (token != NULL && chIndex < 6) {
      channels[chIndex] = atoi(token); // Convert string to integer
      token = strtok(NULL, ",");
      chIndex++;
    }

    // Reset the failsafe timer since we received valid data
    lastPacketTime = millis();
  }

  // --- B. ENFORCE FAILSAFE ---
  if (millis() - lastPacketTime > FAILSAFE_TIMEOUT_MS) {
    // Connection lost! Force safe values.
    channels[0] = 1500; // Roll
    channels[1] = 1500; // Pitch
    channels[2] = 1000; // Throttle (Motors OFF)
    channels[3] = 1500; // Yaw
    channels[4] = 1000; // Arm (Disarm motors)
    channels[5] = 1500; // Aux 2
  }

  // --- C. SEND IBUS TO FLIGHT CONTROLLER AT 50HZ ---
  if (millis() - lastIbusTime >= IBUS_INTERVAL_MS) {
    lastIbusTime = millis();
    sendIBUS(channels);
  }
}

// ==========================================
// 5. NATIVE IBUS PROTOCOL GENERATOR
// ==========================================
// This function packages our channel numbers into standard IBUS hex bytes.
// Betaflight natively understands this format.
void sendIBUS(uint16_t* chValues) {
  uint8_t ibusFrame[32];

  // IBUS Header
  ibusFrame[0] = 0x20; // Length of frame (32 bytes)
  ibusFrame[1] = 0x40; // Command (0x40 means channel data)

  uint16_t checksum = 0xFFFF - ibusFrame[0] - ibusFrame[1];

  // Fill in 14 channels (We only actively use the first 6)
  for (int i = 0; i < 14; i++) {
    uint16_t val = (i < 6) ? chValues[i] : 1500; // Default unused channels to 1500

    // Clamp values to safe RC limits (1000-2000)
    if (val < 1000) val = 1000;
    if (val > 2000) val = 2000;

    // Convert to Little-Endian bytes
    ibusFrame[i * 2 + 2] = val & 0xFF;           // Low byte
    ibusFrame[i * 2 + 3] = (val >> 8) & 0xFF;    // High byte

    // Subtract bytes from checksum
    checksum -= ibusFrame[i * 2 + 2];
    checksum -= ibusFrame[i * 2 + 3];
  }

  // Add checksum to the end of the frame
  ibusFrame[30] = checksum & 0xFF;
  ibusFrame[31] = (checksum >> 8) & 0xFF;

  // Send the frame out of TX2 to the Flight Controller
  Serial2.write(ibusFrame, 32);
}