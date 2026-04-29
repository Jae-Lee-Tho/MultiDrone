// FlightController/Betaflight.js
//
// Simulates the FC's UART RX pad + Betaflight's MSP parser.
// Decodes real MSP SET_RAW_RC packets byte-for-byte, the same
// way actual Betaflight firmware processes them on hardware.

const MSP_SET_RAW_RC = 200;

let lastSerialPacketTime = Date.now();

// ==========================================
// MSP PARSER STATE MACHINE
// Mirrors Betaflight's internal mspSerialProcessReceivedData()
// States: IDLE -> HEADER_M -> HEADER_ARROW ->
//         SIZE -> CMD -> PAYLOAD -> CHECKSUM
// ==========================================
const State = {
    IDLE:         0,
    HEADER_M:     1,
    HEADER_ARROW: 2,
    SIZE:         3,
    CMD:          4,
    PAYLOAD:      5,
    CHECKSUM:     6,
};

let parserState   = State.IDLE;
let payloadSize   = 0;
let command       = 0;
let checksum      = 0;
let payloadBuffer = [];

function parseByte(byte) {
    switch (parserState) {
        case State.IDLE:
            if (byte === 0x24) parserState = State.HEADER_M;
            break;
        case State.HEADER_M:
            parserState = (byte === 0x4D) ? State.HEADER_ARROW : State.IDLE;
            break;
        case State.HEADER_ARROW:
            parserState = (byte === 0x3C) ? State.SIZE : State.IDLE;
            break;
        case State.SIZE:
            payloadSize   = byte;
            checksum      = byte;
            payloadBuffer = [];
            parserState   = State.CMD;
            break;
        case State.CMD:
            command     = byte;
            checksum   ^= byte;
            parserState = payloadSize > 0 ? State.PAYLOAD : State.CHECKSUM;
            break;
        case State.PAYLOAD:
            payloadBuffer.push(byte);
            checksum ^= byte;
            if (payloadBuffer.length === payloadSize) {
                parserState = State.CHECKSUM;
            }
            break;
        case State.CHECKSUM:
            if (byte !== checksum) {
                console.log(`[FC] MSP checksum FAIL — expected 0x${checksum.toString(16)}, got 0x${byte.toString(16)}`);
            } else {
                dispatchCommand(command, payloadBuffer);
            }
            parserState = State.IDLE;
            break;
    }
}

let currentRc = [1500, 1500, 1000, 1500, 1000];

function dispatchCommand(cmd, payload) {
    if (cmd === MSP_SET_RAW_RC) {
        const channelCount = Math.floor(payload.length / 2);
        const channels = [];
        for (let i = 0; i < channelCount; i++) {
            channels.push(payload[i * 2] | (payload[i * 2 + 1] << 8));
        }
        currentRc = channels;
        lastSerialPacketTime = Date.now();
        renderChannels(channels);
    } else if (cmd === 108) { // MSP_ATTITUDE
        // Simulate physical tilt based on RC inputs
        // Roll: 1500 -> 0 degrees, 1600 -> +10.0 degrees (stored as 100)
        const simRoll = (currentRc[0] - 1500);
        const simPitch = -(currentRc[1] - 1500); // Forward pitch drops nose
        const simYaw = (currentRc[3] - 1500);

        const buf = Buffer.alloc(6);
        buf.writeInt16LE(simRoll, 0);
        buf.writeInt16LE(simPitch, 2);
        buf.writeInt16LE(simYaw, 4);

        sendResponse(108, buf);
    } else if (cmd === 110) { // MSP_ANALOG
        const buf = Buffer.alloc(7);
        // Simulate battery voltage (e.g. 24.0V on a 6S battery -> 240)
        buf.writeUInt8(240, 0);
        // mAh drawn placeholder
        buf.writeUInt16LE(0, 1);
        // Simulate Amperage draw based on throttle and movement
        const baseCurrent = (currentRc[2] > 1100) ? 1500 : 50; // 15A flying, 0.5A idle
        const moveCurrent = Math.abs(currentRc[1] - 1500) + Math.abs(currentRc[0] - 1500);
        buf.writeUInt16LE(baseCurrent + moveCurrent, 3); // Amperage (in 0.01A steps)

        sendResponse(110, buf);
    } else {
        console.log(`[FC] Unknown MSP command: ${cmd}`);
    }
}

function sendResponse(cmd, payloadBuf) {
    const packet = Buffer.alloc(6 + payloadBuf.length);
    packet[0] = 0x24; // '$'
    packet[1] = 0x4D; // 'M'
    packet[2] = 0x3E; // '>'
    packet[3] = payloadBuf.length;
    packet[4] = cmd;

    let checksum = packet[3] ^ packet[4];
    for(let i=0; i<payloadBuf.length; i++) {
        packet[5+i] = payloadBuf[i];
        checksum ^= payloadBuf[i];
    }
    packet[5+payloadBuf.length] = checksum;

    if (module.exports.onSerialData) {
        module.exports.onSerialData(packet);
    }
}

function renderChannels(channels) {
    console.clear();
    console.log(`=== FLIGHT CONTROLLER (BETAFLIGHT) ===`);
    console.log(`[MSP] SET_RAW_RC packet decoded OK`);
    console.log(`[CH1] Roll     : ${channels[0] ?? '---'}`);
    console.log(`[CH2] Pitch    : ${channels[1] ?? '---'}`);
    console.log(`[CH3] Throttle : ${channels[2] ?? '---'}`);
    console.log(`[CH4] Yaw      : ${channels[3] ?? '---'}`);
    console.log(`[CH5] Arm/Aux1 : ${channels[4] ?? '---'}`);
}

function receiveSerialData(mspBuffer) {
    for (const byte of mspBuffer) {
        parseByte(byte);
    }
}

setInterval(() => {
    if (Date.now() - lastSerialPacketTime > 500) {
        console.clear();
        console.log("=== FLIGHT CONTROLLER (BETAFLIGHT) ===");
        console.log("!!! FAILSAFE TRIGGERED !!!");
        console.log("No valid MSP packet from ESP32 for > 500ms.");
        console.log("Action: Motors OFF (Throttle 1000), Auto-leveling...");
    }
}, 100);

module.exports = { receiveSerialData };