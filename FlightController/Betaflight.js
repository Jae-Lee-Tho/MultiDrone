// FlightController/Betaflight.js

let lastSerialPacketTime = Date.now();

// This function simulates the physical RX pad on the Flight Controller
function receiveSerialData(channels) {
    lastSerialPacketTime = Date.now();
    console.clear();
    console.log(`=== FLIGHT CONTROLLER (BETAFLIGHT) ===`);
    console.log(`[CH1] Roll     : ${channels[0]}`);
    console.log(`[CH2] Pitch    : ${channels[1]}`);
    console.log(`[CH3] Throttle : ${channels[2]}`);
    console.log(`[CH4] Yaw      : ${channels[3]}`);
    console.log(`[CH5] Arm/Aux1 : ${channels[4]}`);
}

// The Failsafe Loop running on the Flight Controller
setInterval(() => {
    if (Date.now() - lastSerialPacketTime > 500) {
        console.clear();
        console.log("=== FLIGHT CONTROLLER (BETAFLIGHT) ===");
        console.log("!!! FAILSAFE TRIGGERED !!!");
        console.log("No valid serial connection from ESP32 for > 500ms.");
        console.log("Action: Motors OFF (Throttle 1000), Auto-leveling...");
    }
}, 100);

module.exports = { receiveSerialData };