// Minimal DOM contract test for the inline, network-free replay script.
// This verifies interactions and exact nanosecond display, not browser rendering.
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const embedded = html.match(/<script[^>]*id="evidence"[^>]*>([\s\S]*?)<\/script>/)[1];
const script = html.match(/<script>\n([\s\S]*?)<\/script>/)[1];
class Element {
  constructor() { this.children=[]; this.listeners={}; this.value=''; this.dataset={}; this.attributes={}; this.textContent=''; this.disabled=false; }
  append(child) { this.children.push(child); if(this.value==='')this.value=child.value; }
  addEventListener(event, listener) { this.listeners[event]=listener; }
  setAttribute(key, value) { this.attributes[key]=value; }
  replaceChildren() { this.children=[]; }
}
const elements = new Map();
const rows = [{dataset:{knowledge:'observed'}}, {dataset:{knowledge:'inferred'}}, {dataset:{knowledge:'unknown'}}];
const document = {
  getElementById(id) { if(!elements.has(id))elements.set(id,new Element()); return elements.get(id); },
  createElement() { return new Element(); },
  createElementNS() { return new Element(); },
  querySelectorAll() { return rows; },
};
document.getElementById('evidence').textContent=embedded;
vm.runInNewContext(script, {document, Map, Set, JSON, BigInt, Number, String, Math, Infinity});
const get=id=>document.getElementById(id);
if(process.argv[3]==='--integration'){
  assert.equal(get('stream').children.length,4);
  assert.match(get('record').textContent,/oak_rgb_depth/);
  get('stream').value='perception_advisory';get('stream').listeners.change();
  assert.match(get('record').textContent,/DISABLED/);
  get('slot').value='2';get('slot').listeners.input();
  assert.equal(JSON.parse(get('record').textContent).record.frame_id,'2');
  assert.equal(JSON.parse(embedded).geometry.full_3d_traversability,'UNKNOWN');
  console.log('Four-stream diagnostic replay DOM interactions passed.');
  process.exit(0);
}
assert.match(get('alignment').textContent, /unknown/);
assert.equal(get('stream').children.length, 1);
assert.match(get('position').textContent, /9007199254740993/);
assert.match(get('sample').textContent, /9007199254740993/);
assert.equal(get('timeline').children.length, 3);
assert.equal(get('previous').disabled, true);
get('next').listeners.click();
assert.match(get('position').textContent, /Record 2 \/ 3/);
assert.equal(get('previous').disabled, false);
get('replay').value='2'; get('replay').listeners.input();
assert.match(get('position').textContent, /Record 3 \/ 3/);
assert.equal(get('next').disabled, true);
get('timeline').children[0].listeners.click();
assert.match(get('position').textContent, /Record 1 \/ 3/);
get('knowledge').listeners.change({target:{value:'inferred'}});
assert.deepEqual(rows.map(row=>row.hidden), [true, false, true]);
get('knowledge').listeners.change({target:{value:'all'}});
assert.deepEqual(rows.map(row=>row.hidden), [false, false, false]);
console.log('Replay DOM interactions and exact nanosecond display passed.');
