import fs from 'node:fs';
import crypto from 'node:crypto';
const [mode, input, output] = process.argv.slice(2);
const key = Buffer.from(process.env.SOURCE_ARCHIVE_KEY || '', 'hex');
if (key.length !== 32) throw new Error('Build key unavailable');
const data = fs.readFileSync(input);
if (mode === 'open') {
  if (data.subarray(0, 4).toString() !== 'AKB1') throw new Error('Invalid encrypted snapshot');
  const d = crypto.createDecipheriv('aes-256-gcm', key, data.subarray(4, 16));
  d.setAuthTag(data.subarray(16, 32));
  fs.writeFileSync(output, Buffer.concat([d.update(data.subarray(32)), d.final()]));
} else if (mode === 'seal') {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', key, iv);
  const encrypted = Buffer.concat([c.update(data), c.final()]);
  fs.writeFileSync(output, Buffer.concat([Buffer.from('AKB1'), iv, c.getAuthTag(), encrypted]));
} else throw new Error('Invalid operation');
