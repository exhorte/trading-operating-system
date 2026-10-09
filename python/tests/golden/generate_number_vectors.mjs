// Golden vectors for trading_os/shared/numbers.py: what JavaScript itself says for Math.round, toFixed and String(number).
// Run (any Node):  node python/tests/golden/generate_number_vectors.mjs
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const fixed = [
  0.5, 1.5, 2.5, 3.5, -0.5, -1.5, -2.5, 0.49999999999999994, 1.005, 1.45, 8.345, 0.125, 0.375, 2.675, 10.235, 0.0005, 0.00049999,
  0.25, 0.2501, 2.995, 3, 0.3, 0.1 + 0.2, 1e-7, 1.5e-7, 123456.789, 1e20, 1e21, 1.5e21, -1e21, 5e-324, 1.7976931348623157e308,
  100, 0, -0, 1, -1, 0.000001, 0.0000001, 123456789012345680000, 4.35, 4.345, 1.0000000000000002,
];
const rand = mulberry32(7);
for (let i = 0; i < 400; i += 1) {
  const magnitude = 10 ** Math.floor(rand() * 12 - 6);
  fixed.push((rand() - 0.5) * 2 * magnitude);
}
for (let i = 0; i < 200; i += 1) fixed.push(Math.round(rand() * 2000 - 1000) / 8); // exact binary ties
for (let i = 0; i < 100; i += 1) fixed.push(Math.round(rand() * 100000) / 1000); // typical decimal prices

const rows = fixed.map((value) => {
  const toFixed = {};
  for (const digits of [0, 1, 2, 3, 4]) {
    toFixed[digits] = Math.abs(value) < 1e21 ? value.toFixed(digits) : null;
  }
  return { value: Object.is(value, -0) ? "-0" : value, round: Object.is(Math.round(value), -0) ? 0 : Math.round(value), toFixed, string: String(value) };
});

writeFileSync(join(dirname(fileURLToPath(import.meta.url)), "numbers.json"), JSON.stringify({ rows }));
console.log(`numbers.json written: ${rows.length} values`);
