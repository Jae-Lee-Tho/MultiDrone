// =============================================================================
// VIRTUAL ESP32 + BETAFLIGHT SIMULATOR (Node.js)
// =============================================================================

const dgram = require('dgram');

const UDP_PORT = 4210;
const TELEMETRY_PORT = 4212;

const server = dgram.createSocket('udp4');
const telemetryClient = dgram.createSocket('udp4');

let laptopIP = null;
let laptopConnected = false;

let lastUdpPacketTime = Date.now();
let watchdogTriggered = false;
const WATCHDOG_TIMEOUT_MS = 500;

let droneState = {
    attitude: { roll: 0.0, pitch: 0.0, yaw: 0 },
    analog:   { vbat: 16.8, current: 0.5 },
    bci_rc:   { roll: 1500, pitch: 1500, yaw: 1500, throttle: 1000, arm: 1000 },
    phys_rc:  { roll: 1500, pitch: 1500, yaw: 1500, throttle: 1000 }
};

// =============================================================================
// 1. INCOMING UDP SERVER
// =============================================================================

server.on('listening', () => {
    console.log(`[ESP32 SIM] Virtual ESP32 listening for UDP on port ${UDP_PORT}`);
});

server.on('message', (msg, rinfo) => {
    laptopIP = rinfo.address;
    laptopConnected = true;
    lastUdpPacketTime = Date.now();

    if (watchdogTriggered) watchdogTriggered = false;

    const payload = msg.toString().trim();
    const channels = payload.split(',');

    if (channels.length >= 5) {
        // Corrected mapping: Roll, Pitch, Yaw, Throttle, Arm
        droneState.bci_rc.roll     = parseInt(channels[0]);
        droneState.bci_rc.pitch    = parseInt(channels[1]);
        droneState.bci_rc.yaw      = parseInt(channels[2]);
        droneState.bci_rc.throttle = parseInt(channels[3]);
        droneState.bci_rc.arm      = parseInt(channels[4]);
    }
});

server.bind(UDP_PORT);

// =============================================================================
// 2. LIVE TERMINAL DASHBOARD (Imported from betaflight.js)
// =============================================================================

setInterval(() => {
    console.clear();
    console.log(`=== VIRTUAL FLIGHT CONTROLLER (BETAFLIGHT) ===`);

    if (watchdogTriggered) {
        console.log(`[STATUS] 🚨 FAILSAFE TRIGGERED! Motors OFF.`);
    } else if (laptopConnected) {
        console.log(`[STATUS] ✅ Connected to Laptop BCI (${laptopIP})`);
    } else {
        console.log(`[STATUS] ⏳ Waiting for UDP connection on port ${UDP_PORT}...`);
    }

    console.log(`\n--- INCOMING BCI CHANNELS ---`);
    console.log(`[CH1] Roll     : ${droneState.bci_rc.roll}`);
    console.log(`[CH2] Pitch    : ${droneState.bci_rc.pitch}`);
    console.log(`[CH3] Yaw      : ${droneState.bci_rc.yaw}`);
    console.log(`[CH4] Throttle : ${droneState.bci_rc.throttle}`);
    console.log(`[CH5] Arm/Aux1 : ${droneState.bci_rc.arm}`);

    console.log(`\n--- DRONE TELEMETRY ---`);
    console.log(`Battery: ${droneState.analog.vbat.toFixed(1)}V  |  Amps: ${droneState.analog.current.toFixed(1)}A`);
    console.log(`Roll Angle: ${droneState.attitude.roll.toFixed(1)}° | Pitch Angle: ${droneState.attitude.pitch.toFixed(1)}°`);

}, 100); // Update the screen 10 times a second


// =============================================================================
// 3. VIRTUAL PHYSICS ENGINE
// =============================================================================

setInterval(() => {
    const targetRoll  = (droneState.bci_rc.roll - 1500) / 10.0;
    const targetPitch = (droneState.bci_rc.pitch - 1500) / 10.0;

    droneState.attitude.roll  += (targetRoll - droneState.attitude.roll) * 0.1;
    droneState.attitude.pitch += (targetPitch - droneState.attitude.pitch) * 0.1;

    if (droneState.bci_rc.arm > 1500) {
        droneState.analog.vbat -= 0.0001;
        droneState.analog.current = 5.0 + ((droneState.bci_rc.throttle - 1000) / 100.0) * 15;
    } else {
        droneState.analog.current = 0.5;
    }

    droneState.phys_rc.roll  = 1500 + Math.floor(Math.random() * 3 - 1);
    droneState.phys_rc.pitch = 1500 + Math.floor(Math.random() * 3 - 1);
}, 20);


// =============================================================================
// 4. FAILSAFE WATCHDOG
// =============================================================================

setInterval(() => {
    if (laptopConnected && !watchdogTriggered && (Date.now() - lastUdpPacketTime > WATCHDOG_TIMEOUT_MS)) {
        droneState.bci_rc.roll     = 1500;
        droneState.bci_rc.pitch    = 1500;
        droneState.bci_rc.yaw      = 1500;
        droneState.bci_rc.throttle = 1000;
        droneState.bci_rc.arm      = 1000;
        watchdogTriggered = true;
    }
}, 100);


// =============================================================================
// 5. TELEMETRY BROADCASTERS
// =============================================================================

function sendTelemetry(jsonObj) {
    if (!laptopConnected || !laptopIP) return;
    const msgBuffer = Buffer.from(JSON.stringify(jsonObj));
    telemetryClient.send(msgBuffer, TELEMETRY_PORT, laptopIP);
}

setInterval(() => {
    sendTelemetry({
        type:  "attitude",
        roll:  parseFloat(droneState.attitude.roll.toFixed(1)),
        pitch: parseFloat(droneState.attitude.pitch.toFixed(1)),
        yaw:   Math.round(droneState.attitude.yaw)
    });

    sendTelemetry({
        type:     "rc",
        roll:     droneState.phys_rc.roll,
        pitch:    droneState.phys_rc.pitch,
        yaw:      droneState.phys_rc.yaw,
        throttle: droneState.phys_rc.throttle
    });
}, 100);

setInterval(() => {
    sendTelemetry({
        type:    "analog",
        vbat:    parseFloat(droneState.analog.vbat.toFixed(1)),
        current: parseFloat(droneState.analog.current.toFixed(2))
    });
}, 500);