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

function dispatchCommand(cmd, payload) {
    if (cmd !== MSP_SET_RAW_RC) {
        console.log(`[FC] Unknown MSP command: ${cmd}`);
        return;
    }
    const channelCount = Math.floor(payload.length / 2);
    const channels = [];
    for (let i = 0; i < channelCount; i++) {
        channels.push(payload[i * 2] | (payload[i * 2 + 1] << 8));
    }
    lastSerialPacketTime = Date.now();
    renderChannels(channels);
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