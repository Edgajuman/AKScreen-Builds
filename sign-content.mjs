import fs from 'node:fs';
import crypto from 'node:crypto';
const [input,output]=process.argv.slice(2);
if(fs.existsSync(input)){
  const payload=fs.readFileSync(input,'utf8');
  if(Buffer.byteLength(payload)>4*1024*1024)throw new Error('Payload too large');
  const signature=crypto.sign(null,Buffer.from(payload),process.env.CONTENT_SIGNING_KEY).toString('hex');
  fs.writeFileSync(output,JSON.stringify({payload,signature}));fs.unlinkSync(input);
}
