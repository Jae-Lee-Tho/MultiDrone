// =============================================================================
// DRONE VOICE CONTROL — ESP32 FIRMWARE
// =============================================================================
//
// WHAT THIS FILE DOES:
//   Acts as a wireless bridge between the Raspberry Pi and the flight
//   controller. It receives simple CSV channel values from the Pi over
//   Wi-Fi (UDP), encodes them into a real MSP packet (the protocol
//   Betaflight speaks), and writes those bytes over UART to the FC.
//
// HOW IT FITS INTO THE FULL SYSTEM:
//
//   [Raspberry Pi] ──► Wi-Fi UDP ──► [ESP32] ──► UART TX ──► [Betaflight FC]
//                                   (this file)
//
// HOW TO UPLOAD:
//   1. Open Arduino IDE
//   2. Install board: "esp32 by Espressif Systems" via Board Manager
//   3. Select board: Tools → Board → "ESP32 Dev Module"
//   4. Select the correct COM/USB port
//   5. Click Upload
//
// BEFORE UPLOADING TO REAL HARDWARE — CHECKLIST:
//   □ 1. Set WIFI_MODE to SOFTAP (see Section 1 below)
//   □ 2. Confirm FC_TX_PIN matches which pad you soldered on the FC
//   □ 3. Confirm FC_SERIAL_BAUD matches the MSP port baud rate in
//         Betaflight Configurator → Ports tab (default is 115200)
//   □ 4. In Betaflight Configurator → Ports tab, set the UART that
//         your ESP32 TX wire lands on to "MSP" (not Serial RX)
//
// =============================================================================

#include <WiFi.h>
#include <WiFiUDP.h>


// =============================================================================
// SECTION 1 — WI-FI CONFIGURATION
// =============================================================================
// Two modes available. Change WIFI_MODE to switch between them.
//
//   SOFTAP mode  → ESP32 creates its own Wi-Fi hotspot.
//                  The Raspberry Pi connects directly to the ESP32.
//                  Best for flying: no phone, no router dependency.
//                  ESP32's IP will be 192.168.4.1 (update ESP32_IP in
//                  raspberry_pi.py to match).
//
//   CLIENT mode  → ESP32 joins an existing network (your phone hotspot
//                  or a router). Easier to set up but adds a middleman.
//                  Check your phone's connected-devices list for the
//                  ESP32's assigned IP, then update raspberry_pi.py.
//
// ✏️  Change WIFI_MODE before uploading to real hardware.
// =============================================================================

#define WIFI_SOFTAP  0   // ESP32 creates its own hotspot (recommended for flying)
#define WIFI_CLIENT  1   // ESP32 joins an existing network (phone hotspot, router)

#define WIFI_MODE    WIFI_CLIENT   // ✏️  change to WIFI_SOFTAP for real hardware

const char* WIFI_SSID     = "Drone_Network";   // ✏️  your hotspot name
const char* WIFI_PASSWORD = "dronepass123";    // ✏️  your hotspot password

const uint16_t UDP_PORT = 4210;   // must match ESP32_PORT in raspberry_pi.py


// =============================================================================
// SECTION 2 — UART / SERIAL TO FLIGHT CONTROLLER
// =============================================================================
// The ESP32 sends MSP packets to Betaflight over a physical wire:
//   ESP32 GPIO TX pin  →  FC UART RX pad
//
// ✏️  FC_TX_PIN: check your specific ESP32 board's pinout diagram.
//     GPIO 17 is the default TX for Serial1 on most ESP32 dev boards,
//     but some boards label it differently. Verify before soldering.
//
// ✏️  FC_SERIAL_BAUD: must match the baud rate set in Betaflight
//     Configurator → Ports tab for the UART you're using (default 115200).
//
// NOTE: FC_RX_PIN is not used (we only send, never receive from the FC
//       in this project) but Serial1.begin() requires it.
// =============================================================================

#define FC_SERIAL      Serial1
#define FC_TX_PIN      17      // ✏️  GPIO pin wired to FC's UART RX pad
#define FC_RX_PIN      16      // unused — Serial1.begin() requires a value
#define FC_SERIAL_BAUD 115200  // ✏️  must match Betaflight Ports tab baud rate


// =============================================================================
// SECTION 3 — MSP PROTOCOL CONSTANTS
// =============================================================================
// MSP (MultiWii Serial Protocol) is the serial language Betaflight uses.
// SET_RAW_RC (command 200) tells Betaflight to use our values as if they
// came from a real RC receiver.
//
// Packet structure:
//   '$'  'M'  '<'  [payload_size]  [command]  [payload bytes...]  [checksum]
//
// Each RC channel is a uint16 (2 bytes, little-endian), so 5 channels = 10 bytes.
// Checksum = XOR of every byte from payload_size onward (not including the header).
// =============================================================================

#define MSP_SET_RAW_RC   200
#define RC_CHANNEL_COUNT 5    // roll, pitch, throttle, yaw, arm — must match Pi


// =============================================================================
// SECTION 4 — GLOBALS
// =============================================================================

WiFiUDP udp;
char    udpBuffer[64];   // large enough for "1500,1500,1000,1500,1000\0"

IPAddress piIP;
bool      piConnected = false;
const uint16_t TELEMETRY_PORT = 4212; // Port test_runner.py listens on

// =============================================================================
// SECTION 4.5 — MSP TELEMETRY PARSER
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
            // '>' means FC sending to ESP
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
                if(mspCommand == 108 && piConnected) { // MSP_ATTITUDE
                    int16_t roll = mspPayloadBuffer[0] | (mspPayloadBuffer[1] << 8);
                    int16_t pitch = mspPayloadBuffer[2] | (mspPayloadBuffer[3] << 8);
                    int16_t yaw = mspPayloadBuffer[4] | (mspPayloadBuffer[5] << 8);

                    // Convert integer tenths of a degree to floats
                    float rollDeg = roll / 10.0;
                    float pitchDeg = pitch / 10.0;

                    char jsonBuf[128];
                    snprintf(jsonBuf, sizeof(jsonBuf),
                             "{\"type\":\"attitude\",\"roll\":%.1f,\"pitch\":%.1f,\"yaw\":%d}",
                             rollDeg, pitchDeg, yaw);

                    udp.beginPacket(piIP, TELEMETRY_PORT);
                    udp.print(jsonBuf);
                    udp.endPacket();
                } else if(mspCommand == 110 && piConnected) { // MSP_ANALOG
                    float vbat = mspPayloadBuffer[0] / 10.0;
                    float current = (mspPayloadBuffer[3] | (mspPayloadBuffer[4] << 8)) / 100.0;

                    char jsonBuf[128];
                    snprintf(jsonBuf, sizeof(jsonBuf),
                             "{\"type\":\"analog\",\"vbat\":%.1f,\"current\":%.2f}",
                             vbat, current);

                    udp.beginPacket(piIP, TELEMETRY_PORT);
                    udp.print(jsonBuf);
                    udp.endPacket();
                }
            }
            parserState = IDLE;
            break;
    }
}


// =============================================================================
// SECTION 5 — MSP PACKET BUILDER
// =============================================================================
// Encodes an array of RC channel values into a binary MSP SET_RAW_RC packet
// and writes the raw bytes to the FC over UART.
//
// This is the most important function in this file. On simulation it called
// Betaflight.receiveSerialData() in JavaScript — here it calls FC_SERIAL.write().
// The packet bytes are identical either way.
// =============================================================================

void sendMspSetRawRc(uint16_t channels[], uint8_t count) {
    uint8_t payloadSize          = count * 2;           // 2 bytes per channel
    uint8_t packet[6 + count * 2];                      // header(5) + payload + checksum(1)

    // --- Header ---
    packet[0] = '$';               // MSP preamble byte 1
    packet[1] = 'M';               // MSP preamble byte 2
    packet[2] = '<';               // direction: to FC

    // --- Size + command (these two bytes are included in the checksum) ---
    packet[3] = payloadSize;
    packet[4] = MSP_SET_RAW_RC;

    // --- Payload: each channel as uint16 little-endian ---
    uint8_t checksum = 0;
    checksum ^= packet[3];         // XOR size into checksum
    checksum ^= packet[4];         // XOR command into checksum

    for (int i = 0; i < count; i++) {
        uint8_t lo = channels[i] & 0xFF;           // low byte
        uint8_t hi = (channels[i] >> 8) & 0xFF;    // high byte
        packet[5 + i * 2]     = lo;
        packet[5 + i * 2 + 1] = hi;
        checksum ^= lo;
        checksum ^= hi;
    }

    // --- Checksum ---
    packet[5 + payloadSize] = checksum;

    // --- Write to FC over UART ---
    // On simulation this was: Betaflight.receiveSerialData(packet)
    // On real hardware this writes the same bytes to the physical TX pin.
    FC_SERIAL.write(packet, sizeof(packet));
}


// =============================================================================
// SECTION 6 — SETUP (runs once on power-on)
// =============================================================================

void setup() {
    // USB serial for debug output — open Arduino IDE Serial Monitor at 115200
    // to see status messages. Remove Serial.print() calls in final build if needed.
    Serial.begin(115200);
    Serial.println("\n[ESP32] Booting...");

    // --- Start UART to flight controller ---
    FC_SERIAL.begin(FC_SERIAL_BAUD, SERIAL_8N1, FC_RX_PIN, FC_TX_PIN);
    Serial.printf("[ESP32] FC serial started on TX=GPIO%d at %d baud.\n",
                  FC_TX_PIN, FC_SERIAL_BAUD);

    // --- Connect to Wi-Fi ---
    #if WIFI_MODE == WIFI_SOFTAP
        // ESP32 creates its own hotspot — Raspberry Pi connects directly to it.
        // After connecting, update ESP32_IP in raspberry_pi.py to "192.168.4.1".
        WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
        Serial.printf("[ESP32] SoftAP started. SSID: %s\n", WIFI_SSID);
        Serial.printf("[ESP32] Pi should connect to this network, then target IP: 192.168.4.1\n");

    #else
        // ESP32 joins an existing network (phone hotspot or router).
        // After connecting, check your phone/router for the assigned IP and
        // update ESP32_IP in raspberry_pi.py to match.
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        Serial.print("[ESP32] Connecting to Wi-Fi");
        while (WiFi.status() != WL_CONNECTED) {
            delay(500);
            Serial.print(".");
        }
        Serial.println();
        Serial.print("[ESP32] Connected. ESP32 IP address: ");
        Serial.println(WiFi.localIP());
        Serial.println("[ESP32] ✏️  Update ESP32_IP in raspberry_pi.py to the IP above.");
    #endif

    // --- Start listening for UDP packets from the Raspberry Pi ---
    udp.begin(UDP_PORT);
    Serial.printf("[ESP32] Listening for UDP on port %d.\n", UDP_PORT);
    Serial.println("[ESP32] Ready — waiting for Raspberry Pi packets...");
}


// =============================================================================
// SECTION 7 — MAIN LOOP (runs continuously)
// =============================================================================
// Each iteration:
//   1. Check if a UDP packet has arrived from the Raspberry Pi
//   2. Parse the CSV string into RC channel values
//   3. Encode and send an MSP packet to Betaflight over UART
//   4. Periodically request FC telemetry and forward it
// =============================================================================

unsigned long lastMspReq = 0;

void loop() {
    // --- Step 1: Check for incoming UDP packet ---
    int packetSize = udp.parsePacket();
    if (packetSize > 0) {
        piIP = udp.remoteIP();
        piConnected = true;

        int len = udp.read(udpBuffer, sizeof(udpBuffer) - 1);
        if (len > 0) {
            udpBuffer[len] = '\0';         // null-terminate for string parsing

            // --- Step 2: Parse CSV into channel values ---
            uint16_t channels[RC_CHANNEL_COUNT] = {1500, 1500, 1000, 1500, 1000};
            char*   token = strtok(udpBuffer, ",");
            for (int i = 0; i < RC_CHANNEL_COUNT && token != nullptr; i++) {
                channels[i] = (uint16_t)atoi(token);
                token        = strtok(nullptr, ",");
            }

            // --- Step 3: Encode and send MSP packet to Betaflight ---
            sendMspSetRawRc(channels, RC_CHANNEL_COUNT);
        }
    }

    // --- Step 4: Poll Betaflight Telemetry ---
    // Request MSP_ATTITUDE every 100ms (10Hz)
    if (millis() - lastMspReq > 100) {
        lastMspReq = millis();
        requestMsp(108); // 108 = MSP_ATTITUDE
    }

    // Process incoming bytes from Betaflight
    while (FC_SERIAL.available()) {
        parseMspByte(FC_SERIAL.read());
    }
}
