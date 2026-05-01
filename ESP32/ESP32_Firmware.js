// =============================================================================
// VIRTUAL ESP32 + BETAFLIGHT SIMULATOR (Node.js)
// =============================================================================
//
// WHAT THIS DOES:
//   Mocks the hardware layer of the Drone BCI project.
//   - Listens on UDP 4210 for commands from main_bci.py
//   - Simulates drone physics (pitching/rolling based on RC inputs)
//   - Broadcasts Battery, Attitude, and Physical RC telemetry to UDP 4212
//   - Replicates the 500ms UDP Failsafe Watchdog
//
// HOW TO RUN:
//   node esp32_simulator.js
// =============================================================================

const dgram = require('dgram');

const UDP_PORT = 4210;
const TELEMETRY_PORT = 4212;

const server = dgram.createSocket('udp4');
const telemetryClient = dgram.createSocket('udp4');

// Network State
let laptopIP = null;
let laptopConnected = false;

// Watchdog State
let lastUdpPacketTime = Date.now();
let watchdogTriggered = false;
const WATCHDOG_TIMEOUT_MS = 500;

// Virtual Drone State (What Betaflight actually thinks the drone is doing)
let droneState = {
    attitude: { roll: 0.0, pitch: 0.0, yaw: 0 },
    analog:   { vbat: 16.8, current: 0.5 },    // Simulating a full 4S battery

    // Commands coming from Python script over UDP
    bci_rc:   { roll: 1500, pitch: 1500, throttle: 1000, yaw: 1500, arm: 1000 },

    // Fake "physical" radio transmitter sitting on the desk
    phys_rc:  { roll: 1500, pitch: 1500, throttle: 1000, yaw: 1500 }
};

// =============================================================================
// 1. INCOMING UDP SERVER (Mocking ESP32 Wi-Fi RX)
// =============================================================================

server.on('listening', () => {
    console.log(`[ESP32 SIM] Booting...`);
    console.log(`[ESP32 SIM] Virtual ESP32 listening for UDP on port ${UDP_PORT}`);
    console.log(`[ESP32 SIM] Ready — waiting for Laptop packets...`);
});

server.on('message', (msg, rinfo) => {
    laptopIP = rinfo.address;
    laptopConnected = true;
    lastUdpPacketTime = Date.now();

    // Clear Watchdog if we recovered connection
    if (watchdogTriggered) {
        console.log("[ESP32 SIM] UDP connection recovered. Failsafe cleared.");
        watchdogTriggered = false;
    }

    // Parse the CSV "1500,1500,1000,1500,1000"
    const payload = msg.toString().trim();
    const channels = payload.split(',');

    if (channels.length >= 5) {
        droneState.bci_rc.roll     = parseInt(channels[0]);
        droneState.bci_rc.pitch    = parseInt(channels[1]);
        droneState.bci_rc.throttle = parseInt(channels[2]);
        droneState.bci_rc.yaw      = parseInt(channels[3]);
        droneState.bci_rc.arm      = parseInt(channels[4]);
    }
});

server.bind(UDP_PORT);


// =============================================================================
// 2. VIRTUAL PHYSICS ENGINE
// =============================================================================
// Converts RC stick commands into drone pitch/roll angles, and drains the battery

setInterval(() => {
    // A simple mapping: 1500 is flat (0 deg). 1600 is +10 degrees.
    const targetRoll  = (droneState.bci_rc.roll - 1500) / 10.0;
    const targetPitch = (droneState.bci_rc.pitch - 1500) / 10.0;

    // Smoothly interpolate the drone's physical body toward the target angle
    droneState.attitude.roll  += (targetRoll - droneState.attitude.roll) * 0.1;
    droneState.attitude.pitch += (targetPitch - droneState.attitude.pitch) * 0.1;

    // Simulate battery drain and current draw if armed
    if (droneState.bci_rc.arm > 1500) {
        droneState.analog.vbat -= 0.0001; // Slowly drain
        // Higher throttle = more amps drawn
        droneState.analog.current = 5.0 + ((droneState.bci_rc.throttle - 1000) / 100.0) * 15;
    } else {
        droneState.analog.current = 0.5; // Idle current
    }

    // Add tiny random jitter to physical sticks to make data look real
    droneState.phys_rc.roll  = 1500 + Math.floor(Math.random() * 3 - 1);
    droneState.phys_rc.pitch = 1500 + Math.floor(Math.random() * 3 - 1);

}, 20); // Run at 50Hz


// =============================================================================
// 3. FAILSAFE WATCHDOG
// =============================================================================

setInterval(() => {
    if (laptopConnected && !watchdogTriggered && (Date.now() - lastUdpPacketTime > WATCHDOG_TIMEOUT_MS)) {
        console.log("\n[ESP32 SIM] WARNING: UDP timeout! Triggering RX Failsafe (Throttle 1000, Disarm).");

        droneState.bci_rc.roll     = 1500;
        droneState.bci_rc.pitch    = 1500;
        droneState.bci_rc.throttle = 1000;
        droneState.bci_rc.yaw      = 1500;
        droneState.bci_rc.arm      = 1000;

        watchdogTriggered = true;
    }
}, 100);


// =============================================================================
// 4. TELEMETRY BROADCASTERS (Mocking Betaflight MSP Responses)
// =============================================================================

function sendTelemetry(jsonObj) {
    if (!laptopConnected || !laptopIP) return;
    const msgBuffer = Buffer.from(JSON.stringify(jsonObj));
    telemetryClient.send(msgBuffer, TELEMETRY_PORT, laptopIP);
}

// 10Hz Broadcast (Attitude & Physical RC)
setInterval(() => {
    // 108 = MSP_ATTITUDE
    sendTelemetry({
        type:  "attitude",
        roll:  parseFloat(droneState.attitude.roll.toFixed(1)),
        pitch: parseFloat(droneState.attitude.pitch.toFixed(1)),
        yaw:   Math.round(droneState.attitude.yaw)
    });

    // 105 = MSP_RC
    sendTelemetry({
        type:     "rc",
        roll:     droneState.phys_rc.roll,
        pitch:    droneState.phys_rc.pitch,
        throttle: droneState.phys_rc.throttle,
        yaw:      droneState.phys_rc.yaw
    });
}, 100);

// 2Hz Broadcast (Analog / Battery)
setInterval(() => {
    // 110 = MSP_ANALOG
    sendTelemetry({
        type:    "analog",
        vbat:    parseFloat(droneState.analog.vbat.toFixed(1)),
        current: parseFloat(droneState.analog.current.toFixed(2))
    });
}, 500);