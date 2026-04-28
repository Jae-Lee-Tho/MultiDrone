// Tools/rc_sniffer.js
//
// Run this ALONGSIDE the normal stack while flying with your
// physical Radiomaster Pocket controller. It listens to the
// same UDP stream the Pi sends, prints a live channel readout,
// and lets you press a key to tag and save named snapshots.
//
// Usage:
//   node Tools/rc_sniffer.js
//
// While it's running, fly each maneuver manually and press:
//   h — tag current values as "hover"
//   f — tag as "forward"
//   b — tag as "backward"
//   l — tag as "left"
//   r — tag as "right"
//   u — tag as "up" (climb)
//   d — tag as "down" (descend)
//   s — tag as "stop / land"
//   q — quit and print the full reference table
//
// The output gives you exact channel values to paste into
// raspberry_pi.py's apply_command() function.

const dgram = require('dgram');
const readline = require('readline');

const LISTEN_IP   = '127.0.0.1';
const LISTEN_PORT = 4210;

let currentChannels = { roll: 0, pitch: 0, throttle: 0, yaw: 0, arm: 0 };
let snapshots = {};

const MANEUVER_KEYS = {
    h: 'hover',
    f: 'forward',
    b: 'backward',
    l: 'left',
    r: 'right',
    u: 'climb',
    d: 'descend',
    s: 'stop_land',
};

// ---- UDP listener ----
const sock = dgram.createSocket('udp4');
sock.bind(LISTEN_PORT, LISTEN_IP, () => {
    console.log(`\n[RC Sniffer] Listening on ${LISTEN_IP}:${LISTEN_PORT}`);
    console.log(`[RC Sniffer] Fly with physical controller and press keys to tag maneuvers:`);
    console.log(`  h=hover  f=forward  b=backward  l=left  r=right`);
    console.log(`  u=climb  d=descend  s=stop/land  q=quit\n`);
});

sock.on('message', (msg) => {
    const parts = msg.toString().split(',');
    currentChannels = {
        roll:     parseInt(parts[0]),
        pitch:    parseInt(parts[1]),
        throttle: parseInt(parts[2]),
        yaw:      parseInt(parts[3]),
        arm:      parseInt(parts[4]),
    };
    printLive();
});

// ---- Live display ----
function printLive() {
    process.stdout.write(
        `\r  Roll:${pad(currentChannels.roll)}  ` +
        `Pitch:${pad(currentChannels.pitch)}  ` +
        `Thr:${pad(currentChannels.throttle)}  ` +
        `Yaw:${pad(currentChannels.yaw)}  ` +
        `Arm:${pad(currentChannels.arm)}   `
    );
}

function pad(n) {
    return String(n).padStart(4, ' ');
}

// ---- Keyboard input ----
readline.emitKeypressEvents(process.stdin);
if (process.stdin.isTTY) process.stdin.setRawMode(true);

process.stdin.on('keypress', (_, key) => {
    if (!key) return;

    if (key.name === 'q') {
        printSummary();
        process.exit(0);
    }

    const maneuver = MANEUVER_KEYS[key.name];
    if (maneuver) {
        snapshots[maneuver] = { ...currentChannels };
        console.log(`\n  [TAGGED] ${maneuver.toUpperCase()} => Roll:${currentChannels.roll} Pitch:${currentChannels.pitch} Thr:${currentChannels.throttle} Yaw:${currentChannels.yaw}`);
    }
});

// ---- Summary output ----
function printSummary() {
    console.log('\n\n====== RC REFERENCE TABLE ======');
    console.log('Paste these into raspberry_pi.py apply_command()\n');

    if (Object.keys(snapshots).length === 0) {
        console.log('  No maneuvers tagged.');
        return;
    }

    for (const [maneuver, ch] of Object.entries(snapshots)) {
        console.log(`  ${maneuver.toUpperCase().padEnd(12)}: roll=${ch.roll}  pitch=${ch.pitch}  throttle=${ch.throttle}  yaw=${ch.yaw}  arm=${ch.arm}`);
    }

    console.log('\n-- Suggested apply_command() values --');

    if (snapshots.hover)    console.log(`  HOVER throttle  : ${snapshots.hover.throttle}  (replace 1600 in TAKEOFF)`);
    if (snapshots.forward)  console.log(`  FORWARD pitch   : ${snapshots.forward.pitch}   (replace 1700)`);
    if (snapshots.backward) console.log(`  BACKWARD pitch  : ${snapshots.backward.pitch}  (replace 1300)`);
    if (snapshots.left)     console.log(`  LEFT roll       : ${snapshots.left.roll}        (replace 1300)`);
    if (snapshots.right)    console.log(`  RIGHT roll      : ${snapshots.right.roll}       (replace 1700)`);

    console.log('\n================================\n');
}