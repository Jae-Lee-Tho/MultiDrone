// ESP32/ESP32_Firmware.js
const dgram = require('dgram');

// Simulating the physical wire connecting ESP32 TX to FlightController RX
const Betaflight = require('../FlightController/Betaflight.js');

const server = dgram.createSocket('udp4');
const ESP32_IP = '127.0.0.1';
const ESP32_PORT = 4210;

server.on('message', (msg, rinfo) => {
    // 1. Receive UDP string from Raspberry Pi
    const payload = msg.toString();

    // 2. Parse into RC Channels
    const channels = payload.split(',');

    // 3. Send out via Serial to Betaflight
    Betaflight.receiveSerialData(channels);
});

server.bind(ESP32_PORT, ESP32_IP, () => {
    console.log(`[ESP32] SoftAP Wi-Fi network "Drone_Network" started.`);
    console.log(`[ESP32] Listening for Raspberry Pi UDP packets on ${ESP32_IP}:${ESP32_PORT}...`);
    console.log(`[ESP32] TX pin successfully linked to FlightController RX.`);
});