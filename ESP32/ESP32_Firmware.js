// ESP32/ESP32_Firmware.js
const dgram = require('dgram');
const Betaflight = require('../FlightController/Betaflight.js');

const server = dgram.createSocket('udp4');
const telemetryClient = dgram.createSocket('udp4');
const ESP32_IP   = '127.0.0.1';
const ESP32_PORT = 4210;
const TELEMETRY_PORT = 4212;
let piIP = null;

// ==========================================
// MSP ENCODING
// Implements MSP SET_RAW_RC (command 200).
// This is the exact byte sequence the real
// ESP32 would write to its UART TX pin.
// On real hardware: replace serialPort.write()
// with Serial.write() in Arduino/C++.
// ==========================================
const MSP_SET_RAW_RC = 200;
const MSP_ATTITUDE = 108;

function buildMspPacket(channels) {
    // Each channel is a uint16 (2 bytes, little-endian)
    const payloadSize = channels.length * 2;
    const buf = Buffer.alloc(6 + payloadSize);

    buf[0] = 0x24; // '$'
    buf[1] = 0x4D; // 'M'
    buf[2] = 0x3C; // '<'  (to FC direction)
    buf[3] = payloadSize;
    buf[4] = MSP_SET_RAW_RC;

    for (let i = 0; i < channels.length; i++) {
        const val = parseInt(channels[i], 10);
        buf[5 + i * 2]     = val & 0xFF;        // low byte
        buf[5 + i * 2 + 1] = (val >> 8) & 0xFF; // high byte
    }

    // XOR checksum: from payloadSize byte through end of payload
    let checksum = 0;
    for (let i = 3; i < 5 + payloadSize; i++) {
        checksum ^= buf[i];
    }
    buf[5 + payloadSize] = checksum;

    return buf;
}

function requestMsp(cmd) {
    const buf = Buffer.alloc(6);
    buf[0] = 0x24; // '$'
    buf[1] = 0x4D; // 'M'
    buf[2] = 0x3C; // '<'
    buf[3] = 0;    // size
    buf[4] = cmd;  // cmd
    buf[5] = cmd;  // checksum
    Betaflight.receiveSerialData(buf);
}

server.on('message', (msg, rinfo) => {
    piIP = rinfo.address;
    const payload  = msg.toString();
    const channels = payload.split(',');

    // Build a real MSP packet from the channel values
    const mspPacket = buildMspPacket(channels);

    // Send the MSP bytes to the simulated FC.
    // On real hardware this line becomes:
    //   Serial1.write(mspPacket, mspPacket.length);
    Betaflight.receiveSerialData(mspPacket);
});

// Periodically request telemetry from FC
let mspToggle = false;
setInterval(() => {
    if (piIP) {
        requestMsp(mspToggle ? MSP_ATTITUDE : 110); // 110 = MSP_ANALOG
        mspToggle = !mspToggle;
    }
}, 50); // 20Hz polling to alternate requests rapidly

// Receive telemetry from FC and forward to Python test runner
Betaflight.onSerialData = (packet) => {
    // Basic parser for simulated responses
    if (packet[4] === MSP_ATTITUDE) {
        const roll = packet.readInt16LE(5) / 10.0;
        const pitch = packet.readInt16LE(7) / 10.0;
        const yaw = packet.readInt16LE(9);

        const data = JSON.stringify({
            type: 'attitude',
            roll: roll,
            pitch: pitch,
            yaw: yaw
        });

        if (piIP) telemetryClient.send(data, TELEMETRY_PORT, piIP);

    } else if (packet[4] === 110) { // MSP_ANALOG
        const vbat = packet.readUInt8(5) / 10.0;
        const current = packet.readUInt16LE(8) / 100.0;

        const data = JSON.stringify({
            type: 'analog',
            vbat: vbat,
            current: current
        });

        if (piIP) telemetryClient.send(data, TELEMETRY_PORT, piIP);
    }
};

server.bind(ESP32_PORT, ESP32_IP, () => {
    console.log(`[ESP32] SoftAP Wi-Fi network "Drone_Network" started.`);
    console.log(`[ESP32] Listening for Raspberry Pi UDP on ${ESP32_IP}:${ESP32_PORT}...`);
    console.log(`[ESP32] TX pin linked to FlightController RX (MSP mode).`);
});


