// =============================================================================
// DRONE GROUND CONTROL — ESP32 FIRMWARE
// =============================================================================
//
// WHAT THIS FILE DOES:
//   Acts as a wireless bridge between your Laptop and the flight
//   controller. It receives simple CSV channel values from Python over
//   Wi-Fi (UDP), encodes them into a real MSP packet (the protocol
//   Betaflight speaks), and writes those bytes over UART to the FC.
//
// HOW IT FITS INTO THE FULL SYSTEM:
//
//   [Laptop (Voice+EEG)] ──► Wi-Fi UDP ──► [ESP32] ──► UART TX ──► [Betaflight FC]
//                                         (this file)
//
// HOW TO UPLOAD:
//   1. Open Arduino IDE
//   2. Install board: "esp32 by Espressif Systems" via Board Manager
//   3. Select board: Tools → Board → "ESP32 Dev Module"
//   4. Select the correct COM/USB port
//   5. Click Upload
//
// =============================================================================

#include <WiFi.h>
#include <WiFiUDP.h>


// =============================================================================
// SECTION 1 — WI-FI CONFIGURATION
// =============================================================================

#define WIFI_SOFTAP  0   // ESP32 creates its own hotspot (recommended for flying)
#define WIFI_CLIENT  1   // ESP32 joins an existing network

#define WIFI_MODE    WIFI_SOFTAP   // ✏️  change to WIFI_SOFTAP for real hardware

const char* WIFI_SSID     = "Drone_Network";   // ✏️  your network name
const char* WIFI_PASSWORD = "dronepass123";    // ✏️  your network password

const uint16_t UDP_PORT = 4210;   // must match ESP32_PORT in main_bci.py


// =============================================================================
// SECTION 2 — UART / SERIAL TO FLIGHT CONTROLLER
// =============================================================================

#define FC_SERIAL      Serial1
#define FC_TX_PIN      17      // ✏️  GPIO pin wired to FC's UART RX pad
#define FC_RX_PIN      16      // unused — Serial1.begin() requires a value
#define FC_SERIAL_BAUD 115200  // ✏️  must match Betaflight Ports tab baud rate


// =============================================================================
// SECTION 3 — MSP PROTOCOL CONSTANTS
// =============================================================================

#define MSP_SET_RAW_RC   200
#define RC_CHANNEL_COUNT 5    // roll, pitch, yaw, throttle, arm — must match Python


// =============================================================================
// SECTION 3.5 — TIMING & FAILSAFE CONFIGURATION
// =============================================================================

#define TELEMETRY_ATTITUDE_POLL_MS 100 // ✏️ tune — interval to request roll/pitch/yaw (10Hz)
#define TELEMETRY_ANALOG_POLL_MS   500 // ✏️ tune — interval to request vbat/current (2Hz)
#define WATCHDOG_TIMEOUT_MS        500 // ✏️ tune — disarm if no UDP packet received in this time
#define TELEMETRY_RC_POLL_MS       100 // ✏️ tune — interval to request physical RC sticks (10Hz)


// =============================================================================
// SECTION 4 — GLOBALS
// =============================================================================

WiFiUDP udp;
char    udpBuffer[64];   // large enough for "1500,1500,1500,1000,1000\0"

IPAddress laptopIP;
bool      laptopConnected = false;
const uint16_t TELEMETRY_PORT = 4212; // Port the laptop could listen on

// Failsafe & Telemetry Tracking Timers
unsigned long lastUdpPacketTime = 0;
bool          watchdogTriggered = false;
unsigned long lastAttitudeReq   = 0;
unsigned long lastAnalogReq     = 0;
unsigned long lastRcReq         = 0;
unsigned long lastAltReq        = 0; // For Alt measuring variable


// =============================================================================
// SECTION 5 — MSP TELEMETRY PARSER
// =============================================================================

enum MspState { IDLE, HEADER_M, HEADER_ARROW, SIZE, CMD, PAYLOAD, CHECKSUM };
MspState parserState = IDLE;
uint8_t mspPayloadSize = 0;
uint8_t mspCommand = 0;
uint8_t mspChecksum = 0;
uint8_t mspPayloadBuffer[64];
uint8_t mspPayloadIdx = 0;

void requestMsp(uint8_t cmd) {
    uint8_t req[6] = {'$', 'M', '<', 0, cmd, cmd};
    FC_SERIAL.write(req, 6);
}

void parseMspByte(uint8_t c) {
    switch(parserState) {
        case IDLE:
            if(c == '$') parserState = HEADER_M;
            break;
        case HEADER_M:
            parserState = (c == 'M') ? HEADER_ARROW : IDLE;
            break;
        case HEADER_ARROW:
            parserState = (c == '>') ? SIZE : IDLE;
            break;
        case SIZE:
            mspPayloadSize = c;
            mspChecksum = c;
            mspPayloadIdx = 0;
            parserState = CMD;
            break;
        case CMD:
            mspCommand = c;
            mspChecksum ^= c;
            parserState = (mspPayloadSize > 0) ? PAYLOAD : CHECKSUM;
            break;
        case PAYLOAD:
            if(mspPayloadIdx < sizeof(mspPayloadBuffer)) {
                mspPayloadBuffer[mspPayloadIdx++] = c;
            }
            mspChecksum ^= c;
            if(mspPayloadIdx == mspPayloadSize) parserState = CHECKSUM;
            break;
        case CHECKSUM:
            if(c == mspChecksum) {
                // Packet is valid!
                if(mspCommand == 108 && laptopConnected) { // MSP_ATTITUDE
                    int16_t roll = mspPayloadBuffer[0] | (mspPayloadBuffer[1] << 8);
                    int16_t pitch = mspPayloadBuffer[2] | (mspPayloadBuffer[3] << 8);
                    int16_t yaw = mspPayloadBuffer[4] | (mspPayloadBuffer[5] << 8);

                    float rollDeg = roll / 10.0;
                    float pitchDeg = pitch / 10.0;

                    char jsonBuf[128];
                    snprintf(jsonBuf, sizeof(jsonBuf),
                             "{\"type\":\"attitude\",\"roll\":%.1f,\"pitch\":%.1f,\"yaw\":%d}",
                             rollDeg, pitchDeg, yaw);

                    udp.beginPacket(laptopIP, TELEMETRY_PORT);
                    udp.print(jsonBuf);
                    udp.endPacket();
                } else if(mspCommand == 110 && laptopConnected) { // MSP_ANALOG
                    float vbat = mspPayloadBuffer[0] / 10.0;
                    float current = (mspPayloadBuffer[3] | (mspPayloadBuffer[4] << 8)) / 100.0;

                    char jsonBuf[128];
                    snprintf(jsonBuf, sizeof(jsonBuf),
                             "{\"type\":\"analog\",\"vbat\":%.1f,\"current\":%.2f}",
                             vbat, current);

                    udp.beginPacket(laptopIP, TELEMETRY_PORT);
                    udp.print(jsonBuf);
                    udp.endPacket();

                } else if(mspCommand == 109 && laptopConnected) { // MSP_ALTITUDE
                    // FIX: Must explicitly cast to int32_t before shifting to prevent C++ overflow
                    int32_t altCm = (int32_t)mspPayloadBuffer[0] |
                                   ((int32_t)mspPayloadBuffer[1] << 8) |
                                   ((int32_t)mspPayloadBuffer[2] << 16) |
                                   ((int32_t)mspPayloadBuffer[3] << 24);

                    float altMeters = altCm / 100.0;

                    char jsonBuf[128];
                    snprintf(jsonBuf, sizeof(jsonBuf),
                             "{\"type\":\"altitude\",\"alt\":%.2f}",
                             altMeters);

                    udp.beginPacket(laptopIP, TELEMETRY_PORT);
                    udp.print(jsonBuf);
                    udp.endPacket();

                } else if(mspCommand == 105 && laptopConnected) { // MSP_RC
                    // Payload is 16-bit values for Roll, Pitch, Yaw, Throttle
                    int16_t roll     = mspPayloadBuffer[0] | (mspPayloadBuffer[1] << 8);
                    int16_t pitch    = mspPayloadBuffer[2] | (mspPayloadBuffer[3] << 8);
                    int16_t yaw      = mspPayloadBuffer[4] | (mspPayloadBuffer[5] << 8);
                    int16_t throttle = mspPayloadBuffer[6] | (mspPayloadBuffer[7] << 8);

                    char jsonBuf[128];
                    snprintf(jsonBuf, sizeof(jsonBuf),
                             "{\"type\":\"rc\",\"roll\":%d,\"pitch\":%d,\"throttle\":%d,\"yaw\":%d}",
                             roll, pitch, throttle, yaw);

                    udp.beginPacket(laptopIP, TELEMETRY_PORT);
                    udp.print(jsonBuf);
                    udp.endPacket();
                }
            }
            parserState = IDLE;
            break;
    }

}

// =============================================================================
// SECTION 6 — MSP PACKET BUILDER
// =============================================================================

void sendMspSetRawRc(uint16_t channels[], uint8_t count) {
    // Safety check in case count exceeds our buffer layout
    if (count > RC_CHANNEL_COUNT) return;

    uint8_t payloadSize  = count * 2;
    // Fixed size buffer (no VLA) avoiding fragile C99 extensions
    uint8_t packet[6 + (RC_CHANNEL_COUNT * 2)];

    // Header
    packet[0] = '$';
    packet[1] = 'M';
    packet[2] = '<';

    // Size + command
    packet[3] = payloadSize;
    packet[4] = MSP_SET_RAW_RC;

    // Payload
    uint8_t checksum = 0;
    checksum ^= packet[3];
    checksum ^= packet[4];

    for (int i = 0; i < count; i++) {
        uint8_t lo = channels[i] & 0xFF;           // low byte
        uint8_t hi = (channels[i] >> 8) & 0xFF;    // high byte
        packet[5 + i * 2]     = lo;
        packet[5 + i * 2 + 1] = hi;
        checksum ^= lo;
        checksum ^= hi;
    }

    // Checksum
    packet[5 + payloadSize] = checksum;

    // Write to FC over UART (only write the exact valid packet length)
    FC_SERIAL.write(packet, 6 + payloadSize);
}


// =============================================================================
// SECTION 7 — SETUP (runs once on power-on)
// =============================================================================

void setup() {
    Serial.begin(115200);
    Serial.println("\n[ESP32] Booting...");

    // Start UART to flight controller
    FC_SERIAL.begin(FC_SERIAL_BAUD, SERIAL_8N1, FC_RX_PIN, FC_TX_PIN);
    Serial.printf("[ESP32] FC serial started on TX=GPIO%d at %d baud.\n", FC_TX_PIN, FC_SERIAL_BAUD);

    // Connect to Wi-Fi
    #if WIFI_MODE == WIFI_SOFTAP
        WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
        Serial.printf("[ESP32] SoftAP started. SSID: %s\n", WIFI_SSID);
        Serial.printf("[ESP32] Laptop should connect to this network, then target IP: 192.168.4.1\n");

    #else
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        Serial.print("[ESP32] Connecting to Wi-Fi");
        while (WiFi.status() != WL_CONNECTED) {
            delay(500);
            Serial.print(".");
        }
        Serial.println();
        Serial.print("[ESP32] Connected. ESP32 IP address: ");
        Serial.println(WiFi.localIP());
        Serial.println("[ESP32] ✏️  Update ESP32_IP in main_bci.py to the IP above.");
    #endif

    // Start listening for UDP packets from the Laptop
    udp.begin(UDP_PORT);
    Serial.printf("[ESP32] Listening for UDP on port %d.\n", UDP_PORT);
    Serial.println("[ESP32] Ready — waiting for Laptop packets...");
}


// =============================================================================
// SECTION 8 — MAIN LOOP (runs continuously)
// =============================================================================

void loop() {
    unsigned long now = millis();

    // Step 1: Check for incoming UDP packet
    int packetSize = udp.parsePacket();
    if (packetSize > 0) {
        laptopIP = udp.remoteIP();
        laptopConnected = true;

        // Reset Watchdog Timer since we just received data
        lastUdpPacketTime = now;
        if (watchdogTriggered) {
            Serial.println("[ESP32] UDP connection recovered. Failsafe cleared.");
            watchdogTriggered = false;
        }

        int len = udp.read(udpBuffer, sizeof(udpBuffer) - 1);
        if (len > 0) {
            udpBuffer[len] = '\0';

            // Step 2: Parse CSV into channel values
            // FIX: Order is Roll, Pitch, Yaw, Throttle, Arm
            uint16_t channels[RC_CHANNEL_COUNT] = {1500, 1500, 1500, 1000, 1000};
            char* token = strtok(udpBuffer, ",");
            for (int i = 0; i < RC_CHANNEL_COUNT && token != nullptr; i++) {
                channels[i] = (uint16_t)atoi(token);
                token        = strtok(nullptr, ",");
            }

            // Step 3: Encode and send MSP packet to Betaflight
            sendMspSetRawRc(channels, RC_CHANNEL_COUNT);
        }
    }

    // Step 4: UDP Watchdog Failsafe
    // If we haven't received a packet from the laptop recently, disarm and cut throttle.
    if (laptopConnected && !watchdogTriggered && (now - lastUdpPacketTime > WATCHDOG_TIMEOUT_MS)) {
        Serial.println("[ESP32] WARNING: UDP timeout! Triggering RX Failsafe (Throttle 1000, Disarm).");
        // FIX: Order is Roll, Pitch, Yaw, Throttle, Arm
        uint16_t failsafeChannels[RC_CHANNEL_COUNT] = {1500, 1500, 1500, 1000, 1000};
        sendMspSetRawRc(failsafeChannels, RC_CHANNEL_COUNT);
        watchdogTriggered = true;
    }

    // Step 5: Poll Betaflight Telemetry
    // Request MSP_ATTITUDE (roll/pitch)
    if (now - lastAttitudeReq > TELEMETRY_ATTITUDE_POLL_MS) {
        lastAttitudeReq = now;
        requestMsp(108); // 108 = MSP_ATTITUDE
    }

    // Request MSP_ANALOG (vbat/current) staggered from attitude
    if (now - lastAnalogReq > TELEMETRY_ANALOG_POLL_MS) {
        lastAnalogReq = now;
        requestMsp(110); // 110 = MSP_ANALOG
    }

    if (now - lastRcReq > TELEMETRY_RC_POLL_MS) {
        lastRcReq = now;
        requestMsp(105); // 105 = MSP_RC
    }

    // Request MSP_ALTITUDE
    if (now - lastAltReq > 200) { // Poll every 200ms (5Hz)
        lastAltReq = now;
        requestMsp(109); // 109 = MSP_ALTITUDE
    }

    // Process incoming bytes from Betaflight
    while (FC_SERIAL.available()) {
        parseMspByte(FC_SERIAL.read());
    }
}