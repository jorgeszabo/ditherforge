#!/usr/bin/env node
'use strict';
// Obtain resolved configuration through the maintained converter's CLI exporter.
// Only profile data crosses this process boundary; its implementation stays there.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const { parseArgs } = require('node:util');
const root = path.resolve(__dirname, '..');
const { values } = parseArgs({options:{slicer:{type:'string'},converter:{type:'string'}}});
const converter = path.resolve(values.converter || path.join(root, '../3mf-colour-converter'));
const installed = '/Applications/PrusaSlicer-3.0.0-alpha13.app/Contents/MacOS/PrusaSlicer';
const isolated = path.join(root, '.local/deps/PrusaSlicer-3.0.0-alpha13.app/Contents/MacOS/PrusaSlicer');
const binary = fs.existsSync(installed) ? installed : isolated;
const slicer = values.slicer || process.env.PRUSA_SLICER || path.join(root,'scripts/prusaslicer-alpha13');
const local = path.join(root, '.local');
fs.mkdirSync(local,{recursive:true});
const exported = path.join(local, 'indx-profiles.cjs');
const run = spawnSync(process.execPath,[path.join(converter,'tools/refresh-indx.cjs'),'--slicer',slicer,'--output',exported],{stdio:'inherit'});
if(run.status !== 0) process.exit(run.status || 1);
const data = require(exported);
const digest = createHash('sha256').update(fs.readFileSync(exported)).digest('hex');
fs.writeFileSync(path.join(local,'indx-profiles.json'),JSON.stringify(data));
const bedModel = path.join(path.dirname(binary),'../Resources/presets/prusa-research-fff/PrusaResearch/assets/coreoneindx_bed.stl');
fs.writeFileSync(path.join(local,'runtime.json'),JSON.stringify({slicer,converter,bedModel,profileSha256:digest},null,2)+'\n');
const profileRoot = path.join(root,'internal/export3mf/profiles');
const id = 'prusa_coreone_indx_8t';
const dir = path.join(profileRoot,id);
fs.mkdirSync(dir,{recursive:true});
const scalar = v => Array.isArray(v) ? scalar(v[0]) : v;
const mm = (v, diameter=0.4) => { v=scalar(v); return typeof v==='object' ? v.value*(v.is_percent?diameter/100:1) : Number(v); };
const processes = Object.values(data.processes).map(p=>{
  const c = p.printSettings;
  const pp = {layer_height:p.layerHeight,name:p.print.name,file:`process_${p.layerHeight}.json`,line_width:mm(c.extrusion_width),initial_layer_line_width:mm(c.first_layer_extrusion_width),initial_layer_print_height:mm(c.first_layer_height)};
  const raw = {name:p.print.name,layer_height:String(p.layerHeight),initial_layer_print_height:String(pp.initial_layer_print_height),line_width:String(pp.line_width),initial_layer_line_width:String(pp.initial_layer_line_width),outer_wall_line_width:String(mm(c.external_perimeter_extrusion_width)),inner_wall_line_width:String(mm(c.perimeter_extrusion_width)),wall_loops:String(c.perimeters)};
  fs.writeFileSync(path.join(dir,pp.file),JSON.stringify(raw,null,2)+'\n');
  return pp;
});
const machine = {name:data.printerName,printer_model:'COREONE_INDX',printer_variant:'8T HF0.4',nozzle_diameter:Array(8).fill('0.4'),printable_area:data.group.configuration.printer_settings.bed_shape.map(([x,y])=>`${x}x${y}`),printable_height:String(data.group.configuration.printer_settings.max_print_height)};
fs.writeFileSync(path.join(dir,'machine_0.4.json'),JSON.stringify(machine,null,2)+'\n');
const manifestFile = path.join(profileRoot,'manifest.json');
const manifest = JSON.parse(fs.readFileSync(manifestFile));
const printer = {id,display_name:'Prusa CORE One INDX 8T (0.4 HF)',nozzles:[{diameter:'0.4',printer_settings_id:data.printerName,machine_file:'machine_0.4.json',processes}]};
manifest.printers = [printer,...manifest.printers.filter(p=>p.id!==id)];
fs.writeFileSync(manifestFile,JSON.stringify(manifest,null,2)+'\n');
fs.writeFileSync(path.join(root,'chat/processes.json'),JSON.stringify({slicerVersion:data.slicerVersion,vendorVersion:data.vendorVersion,profileSha256:digest,processes,source:'Resolved installed Prusa presets; native configuration kept locally. Refresh with scripts/refresh-indx.cjs.'},null,2)+'\n');
console.log('Refreshed INDX grid profiles and local native configuration. Rebuild scripts/build-indx.sh.');
