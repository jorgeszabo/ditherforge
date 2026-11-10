<script lang="ts">
  import { onMount } from 'svelte';
  import { ArrowDownToLineIcon, ArrowRightIcon, CheckIcon, ChevronDownIcon, CircleCheckIcon, Clock3Icon, FileBoxIcon, FolderOpenIcon, Layers3Icon, Link2Icon, LockKeyholeIcon, PipetteIcon, PlusIcon, RefreshCwIcon, RotateCcwIcon, SaveIcon, SlidersHorizontalIcon, SparklesIcon, XIcon } from '@lucide/svelte';
  import ModelViewer from './lib/components/ModelViewer.svelte';
  import { SharedCamera } from './lib/components/SharedCamera.svelte';

  type Tool = { tool: number; label?: string; type?: string; color?: string; role: string; td?: number | null };
  type Settings = { sizeValue: string; layerHeight: string; dither?: string; meshRepair?: string; brightness?: number; contrast?: number; saturation?: number; upperLayerXYScale?: number; colorSnap?: number; warpPins?: { sourceHex: string; targetHex: string; sigma: number }[] };
  type Validation = { estimatedPrintTime?: string; filamentGrams?: number; toolChangeCount?: number; validation: { warnings: string[] }; printTime?: string[] };
  type Project = { name: string; sourceName: string; settings: Settings; settingsSha256: string; tools: Tool[]; previewReady: boolean; previewKey?: string; printCurrent: boolean; validation?: Validation };
  type Job = { id: string; kind: string; project: string; status: string; error?: string; progress?: string; started?: number };

  let projects = $state<string[]>([]);
  let selected = $state('');
  let project = $state<Project | null>(null);
  let options = $state({ sizeValue: 50, layerHeight: 0.15, dither: 'dlc-d30-p7', meshRepair: 'none', brightness: 0, contrast: 0, saturation: 0, upperLayerXYScale: 1.25, colorSnap: 5 });
  let tools = $state<Tool[]>([]);
  let pins = $state<{ sourceHex: string; targetHex: string; sigma: number }[]>([]);
  let camera = $state(new SharedCamera());
  let viewEpoch = $state(0);
  let dirty = $state(false);
  let previewHash = $state('');
  let error = $state('');
  let notice = $state('');
  let job = $state<Job | null>(null);
  let pending = $state(false);
  let projectName = $state('');
  let view = $state<'compare' | 'source' | 'result'>('compare');
  let uploading = $state(false);
  let pickMode = $state(false);
  let sampledColor = $state('#808080');
  let correctionColor = $state('#0086d6');
  let layerChoices = $state<number[]>([0.10, 0.15, 0.20, 0.25]);
  const busy = $derived(pending || uploading || job?.status === 'running');
  const activeTools = $derived(tools.filter(t => t.role === 'color').length);
  const previewStale = $derived(dirty || previewHash !== project?.settingsSha256);
  const meshQuery = $derived(project?.previewReady ? `name=${encodeURIComponent(project.name)}&key=${project.previewKey}` : '');
  const inputUrl = $derived(meshQuery ? `/api/mesh?${meshQuery}&view=input` : undefined);
  const outputUrl = $derived(meshQuery ? `/api/mesh?${meshQuery}&view=output` : undefined);
  const stage = $derived(job?.progress?.split('\n').filter(Boolean).at(-1)?.replace(/^.*?\] /, '').slice(0, 120) || 'Preparing model…');

  async function api(path: string, body?: object) {
    const response = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-DitherForge': 'local' }, body: JSON.stringify(body) } : undefined);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The local app could not complete this action.');
    return data;
  }

  async function loadProject(name: string, autoPreview = true) {
    error = ''; notice = ''; pending = true;
    try {
      const p: Project = await api(`/api/project?name=${encodeURIComponent(name)}`);
      project = p; selected = p.name;
      const s = p.settings;
      options = { sizeValue: Number(s.sizeValue), layerHeight: Number(s.layerHeight), dither: s.dither || 'dlc-d30-p7', meshRepair: s.meshRepair || 'none', brightness: s.brightness || 0, contrast: s.contrast || 0, saturation: s.saturation || 0, upperLayerXYScale: s.upperLayerXYScale || 1.25, colorSnap: s.colorSnap ?? 5 };
      tools = p.tools.map(t => ({ ...t })); pins = (s.warpPins || []).map(p => ({ ...p }));
      dirty = false; previewHash = p.previewReady ? p.settingsSha256 : ''; resetView();
    } catch (e) { error = String(e); }
    finally { pending = false; }
    if (autoPreview && project && !project.previewReady) await runJob('preview');
  }

  async function refresh() {
    const state = await api('/api/state'); projects = state.projects;
    layerChoices = state.processes.map((p: { layer_height: number }) => p.layer_height);
    if (!selected && projects.length) await loadProject(projects[0]);
  }

  async function switchProject(name: string) {
    try {
      if (dirty) await save();
      await loadProject(name);
    } catch (e) { error = String(e); }
  }

  function pickSource() { view = 'compare'; pickMode = !pickMode; }

  function resetView() { camera = new SharedCamera(); viewEpoch += 1; }

  async function save() {
    if (!project) return;
    const result = await api('/api/configure', { project: project.name, expectedHash: project.settingsSha256, patch: { ...options, tools: $state.snapshot(tools), warpPins: $state.snapshot(pins) } });
    project.settingsSha256 = result.settingsSha256;
    project.printCurrent = false;
    dirty = false; notice = 'Saved. Chat and this workspace now use the same settings.';
  }

  async function saveOnly() {
    pending = true; error = '';
    try { await save(); } catch (e) { error = String(e); } finally { pending = false; }
  }

  async function runJob(kind: 'preview' | 'build') {
    if (!project || busy) return;
    pending = true; error = ''; notice = '';
    try {
      if (dirty) await save();
      const result = await api(`/api/${kind}`, { project: project.name, expectedHash: project.settingsSha256 });
      job = { id: result.id, kind, project: project.name, status: 'running' };
      await poll(result.id);
    } catch (e) { error = String(e); }
    finally { pending = false; }
  }

  async function poll(id: string) {
    const next: Job = await api(`/api/job?id=${id}`); job = next;
    if (next.status === 'running') { window.setTimeout(() => poll(id).catch(e => { error = String(e); pending = false; job = null; }), 850); return; }
    if (next.status === 'error') { error = next.error || 'Generation failed. Your previous print is preserved.'; return; }
    await loadProject(next.project, false);
    notice = next.kind === 'build' ? 'Native project saved after alpha13 reopen and slicing. Previous print revision archived when present.' : 'Preview updated. Rotate either view to compare the same angle.';
  }

  function toggleTool(tool: Tool) {
    if (tool.type === 'PETG') return;
    tool.role = tool.role === 'color' ? 'unassigned' : 'color';
    if (tool.role === 'color') { tool.type ||= 'PLA'; tool.color ||= '#808080'; }
    dirty = true;
  }

  async function importModel(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    uploading = true; error = '';
    try {
      if (dirty) await save();
      const name = projectName.trim() || file.name.replace(/\.[^.]+$/, '').replace(/[+_]/g, ' ');
      const response = await fetch(`/api/import?name=${encodeURIComponent(name)}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-DitherForge': 'local', 'X-Filename': encodeURIComponent(file.name) }, body: file });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      projects = [...projects, result.project].sort(); projectName = ''; uploading = false;
      await loadProject(result.project);
    } catch (e) { error = String(e); }
    finally { uploading = false; input.value = ''; }
  }

  function addPin() {
    if (pins.length >= 8) return;
    pins = [...pins, { sourceHex: sampledColor.toUpperCase(), targetHex: correctionColor.toUpperCase(), sigma: 10 }]; dirty = true;
  }

  onMount(() => {
    refresh().catch(e => { error = String(e); });
    const protectEdits = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', protectEdits);
    return () => window.removeEventListener('beforeunload', protectEdits);
  });
</script>

<div class="studio">
  <header class="studio-header">
    <a class="brand" href="/" aria-label="INDX Colour Studio home"><span class="brand-mark" aria-hidden="true">{#each Array(9) as _, i}<i class:mark-light={i === 2 || i === 6} class:mark-blue={i === 5}></i>{/each}</span><span><strong>INDX<span class="brand-divider">/</span>Colour Studio</strong><small>By DitherForge</small></span></a>
    <div class="header-right"><span class="machine"><span class="machine-dot"></span> CORE One INDX <b>8T</b></span><span class="local-badge"><LockKeyholeIcon size={12}/> Private workspace</span></div>
  </header>
  <div class="studio-layout">
    <aside class="studio-sidebar" aria-label="Project controls">
      <div class="sidebar-scroll">
        <section class="control-section project-section">
          <div class="section-heading"><h2><FolderOpenIcon size={15}/> Project</h2><span class="save-state" class:unsaved={dirty}>{dirty ? 'Unsaved edits' : 'Saved'}</span></div>
          <div class="project-select"><select aria-label="Project" id="project" value={selected} disabled={busy} onchange={async e => { const select = e.currentTarget; await switchProject(select.value); select.value = selected; }}><option value="" disabled>Choose a project</option>{#each projects as name}<option>{name}</option>{/each}</select><button class="icon-button" aria-label="Reload project from disk" title="Reload saved settings" disabled={!project || busy} onclick={() => loadProject(selected)}><RefreshCwIcon size={15}/></button></div>
          <details class="import-panel"><summary><PlusIcon size={14}/> Import a model</summary><label for="new-project">Project name</label><input id="new-project" bind:value={projectName} placeholder="Use model filename" disabled={busy}/><label class:disabled={busy} class="file-button" for="model-file"><FileBoxIcon size={22}/><strong>{uploading ? 'Copying model…' : 'Choose your model'}</strong><span>GLB · 3MF · STL · OBJ · DAE · ZIP</span></label><input id="model-file" class="visually-hidden" type="file" accept=".glb,.3mf,.stl,.obj,.dae,.zip" disabled={busy} onchange={importModel}/><p>Originals stay in your 3D print folder.</p></details>
        </section>
        <section class="control-section tool-section">
          <div class="section-heading"><h2><Layers3Icon size={15}/> Your filaments</h2><span>{activeTools} of 8</span></div><p class="help-text">Your palette. Your physical tool numbers.</p>
          <div class="tool-list">{#each tools as tool (tool.tool)}
            <div class:tool-inactive={tool.role !== 'color'} class:tool-support={tool.type === 'PETG'} class="tool-row">
              <label class="tool-check" title={tool.type === 'PETG' ? 'PETG reserved for supports' : 'Include in colour palette'}><input type="checkbox" aria-label={`Use tool ${tool.tool} for colour`} checked={tool.role === 'color'} disabled={busy || tool.type === 'PETG'} onchange={() => toggleTool(tool)}/><span>T{tool.tool}</span></label>
              <input type="color" aria-label={`Tool ${tool.tool} colour`} value={tool.color || '#808080'} disabled={busy || tool.role !== 'color'} oninput={e => { tool.color = e.currentTarget.value; dirty = true; }}/>
              <div class="spool-fields"><input class="spool-name" aria-label={`Tool ${tool.tool} spool name`} title={tool.label || 'Assign a spool'} value={tool.label || ''} placeholder="Assign a spool" disabled={busy} oninput={e => { tool.label = e.currentTarget.value; dirty = true; }}/><div class="spool-meta"><select aria-label={`Tool ${tool.tool} material`} value={tool.type || ''} disabled={busy} onchange={e => { tool.type = e.currentTarget.value; if (tool.type === 'PETG') tool.role = 'support'; dirty = true; }}><option value="">Unassigned</option><option>PLA</option><option>PETG</option></select>{#if tool.type === 'PETG'}<span class="reserved"><LockKeyholeIcon size={9}/> Support</span>{/if}</div></div>
            </div>
          {/each}</div><p class="help-text">Project assignments · not live spool inventory</p>
        </section>
        <section class="control-section" aria-label="Print and colour settings">
          <div class="section-heading"><h2><SlidersHorizontalIcon size={15}/> Print & colour</h2><span>0.4 HF</span></div>
          <div class="two-fields"><label>Longest side<div class="unit-input"><input aria-label="Longest side in millimetres" type="number" min="1" max="300" bind:value={options.sizeValue} disabled={busy} oninput={() => dirty = true}/><span>mm</span></div></label><label>Layer height<select aria-label="Layer height" bind:value={options.layerHeight} disabled={busy} onchange={() => dirty = true}>{#each layerChoices as h}<option value={h}>{h.toFixed(2)} mm</option>{/each}</select></label></div>
          <label>Dither pattern<select aria-label="Dither pattern" bind:value={options.dither} disabled={busy} onchange={() => dirty = true}><option value="dlc-d30-p7">Dizzy · balanced</option><option value="riemersma">Riemersma</option><option value="floyd-steinberg">Floyd–Steinberg</option><option value="bn-adapt-5">Blue noise</option><option value="none">Solid colours only</option></select></label>
          <label class="range-label">Colour cell size<output>{options.upperLayerXYScale.toFixed(2)}×</output><input aria-label="Colour cell size" type="range" min="1" max="4" step="0.05" bind:value={options.upperLayerXYScale} disabled={busy} oninput={() => dirty = true}/></label><div class="range-endpoints"><span>More detail</span><span>Larger regions</span></div>
          <details class="fine-tuning"><summary>Fine tuning<ChevronDownIcon size={14}/></summary>
            {#each ['brightness', 'contrast', 'saturation'] as key}<label class="range-label">{key[0].toUpperCase() + key.slice(1)}<output>{options[key as 'brightness' | 'contrast' | 'saturation']}</output><input aria-label={key} type="range" min="-100" max="100" value={options[key as 'brightness' | 'contrast' | 'saturation']} disabled={busy} oninput={e => { options[key as 'brightness' | 'contrast' | 'saturation'] = Number(e.currentTarget.value); dirty = true; }}/></label>{/each}
            <label class="range-label">Reduce near-solid speckle<output>{options.colorSnap}</output><input aria-label="Reduce near-solid speckle" type="range" min="0" max="50" bind:value={options.colorSnap} disabled={busy} oninput={() => dirty = true}/></label>
            <label>Mesh repair<select aria-label="Mesh repair" bind:value={options.meshRepair} disabled={busy} onchange={() => dirty = true}><option value="none">Use original geometry</option><option value="fwn">Winding-number remesh</option><option value="alphawrap">Alpha wrap</option></select></label>
          </details>
        </section>
      </div>
      <div class="sidebar-actions"><button class="secondary save-button" disabled={!project || !dirty || busy} onclick={saveOnly}><SaveIcon size={14}/> Save settings</button><button class="primary" disabled={!project || busy} onclick={() => runJob('preview')}><SparklesIcon size={15}/> {busy ? 'Working…' : 'Update preview'}<ArrowRightIcon size={16}/></button></div>
    </aside>
    <main class="studio-main">
      <div class="workspace-heading"><div><p class="eyebrow"><span></span> YOUR COLOUR WORKSPACE</p><h1>{project?.name || 'A little colour. Endless possibilities.'}</h1><p>{project ? project.sourceName : 'Start with a model. Make it your own.'}</p></div><div class="project-status" class:status-stale={dirty || previewStale}><i></i>{!project ? 'Ready to create' : dirty ? 'Unsaved changes' : previewStale ? 'Preview needs an update' : 'All changes saved'}</div></div>
      {#if error}<div class="message error" role="alert">{error}</div>{/if}
      {#if notice}<div class="message success" role="status"><CheckIcon size={16}/><span>{notice}</span></div>{/if}
      {#if busy}<div class="job-status" role="status"><span class="spinner"></span><strong>{job?.kind === 'build' ? 'Validating your print project' : uploading ? 'Importing model' : 'Preparing your preview'}</strong><span>{stage}</span></div>{/if}
      <div class="preview-toolbar"><div class="view-switch" role="group" aria-label="Preview layout">{#each [{id:'compare', label:'Compare'}, {id:'source', label:'Source'}, {id:'result', label:'Result'}] as mode}<button aria-pressed={view === mode.id} class:chosen={view === mode.id} onclick={() => { view = mode.id as typeof view; pickMode = false; }}>{mode.label}</button>{/each}</div><span class="camera-link"><Link2Icon size={12}/> Linked cameras</span><button class="text-button reset-view" disabled={!project} onclick={resetView}><RotateCcwIcon size={14}/> Reset view</button></div>
      <div class="viewer-grid" class:single-view={view !== 'compare'}>
        <section class="viewer-panel" class:viewer-hidden={view === 'result'} aria-label="Source model viewer"><div class="viewer-heading"><h2><span class="viewer-number">01</span>{options.brightness || options.contrast || options.saturation || pins.length ? 'Adjusted source' : 'Source model'}</h2><span class="viewer-tag">ORIGINAL</span></div><div class="viewer-canvas dark">{#key viewEpoch}<ModelViewer meshUrl={inputUrl} label="Source model" showLabel={false} viewerId="hybrid-input" {camera} brightness={options.brightness} contrast={options.contrast} saturation={options.saturation} warpPins={pins.map(p => ({sourceHex:p.sourceHex,targetHex:p.targetHex,sigma:p.sigma}))} {pickMode} onColorPick={hex => { sampledColor = hex; pickMode = false; }} progressActive={false}/>{/key}{#if !inputUrl}<div class="viewer-empty"><FileBoxIcon size={32}/><strong>{busy ? 'Loading your model…' : 'Your next colour print starts here'}</strong><span>Import a model from the project panel.</span></div>{/if}{#if pickMode}<div class="pick-hint"><PipetteIcon size={14}/> Click a colour on the model</div>{/if}</div><div class="viewer-footer"><span>Drag to rotate · Scroll to zoom</span><span>Right-drag to pan</span></div></section>
        <section class="viewer-panel result-panel" class:viewer-hidden={view === 'source'} aria-label="Dithered model viewer"><div class="viewer-heading"><h2><span class="viewer-number">02</span>Dithered preview</h2><span class="viewer-tag" class:needs-update={previewStale}>{previewStale ? 'NEEDS UPDATE' : 'YOUR FILAMENTS'}</span></div><div class="viewer-canvas dark">{#key viewEpoch}<ModelViewer meshUrl={outputUrl} label="Dithered model" showLabel={false} viewerId="hybrid-output" {camera} progressActive={false}/>{/key}{#if !outputUrl}<div class="viewer-empty"><SparklesIcon size={32}/><strong>{busy ? 'Finding your colours…' : 'See what your filaments can do'}</strong><span>Choose your palette, then update the preview.</span></div>{/if}</div><div class="viewer-footer"><span>Print colour preview</span><span>Appearance uncalibrated</span></div></section>
      </div>
      <div class="palette-ribbon"><div class="palette-caption"><span class="eyebrow">THE PALETTE</span><strong>{activeTools} filament{activeTools === 1 ? '' : 's'}</strong></div><div class="palette-swatches">{#each tools.filter(t => t.role === 'color') as tool}<span class="palette-chip" title={tool.label}><i style:background={tool.color}></i>T{tool.tool}</span>{/each}{#if !activeTools}<span class="help-text">Select a filament to begin</span>{/if}</div><span class="process-chip">{options.sizeValue} mm <i>·</i> {options.layerHeight.toFixed(2)} mm layers</span></div>
      <section class="correction-panel" aria-label="Colour corrections"><div class="correction-title"><span class="correction-icon"><PipetteIcon size={18}/></span><div><h2>Fine-tune a colour</h2><p>Sample the source, then choose a target.</p></div></div><div class="correction-controls"><button class:active={pickMode} class="secondary" disabled={!inputUrl || busy} onclick={pickSource}><PipetteIcon size={14}/>{pickMode ? 'Picking…' : 'Pick colour'}</button><div class="colour-pair"><input aria-label="Source correction colour" type="color" bind:value={sampledColor}/><ArrowRightIcon size={13}/><input aria-label="Target correction colour" type="color" bind:value={correctionColor}/></div><button class="icon-button" title="Add correction" aria-label="Add correction" disabled={busy || pins.length >= 8 || !project} onclick={addPin}><PlusIcon size={17}/></button></div>
      {#if pins.length}<div class="correction-list">{#each pins as pin, i}<span class="correction-chip"><i style:background={pin.sourceHex}></i><ArrowRightIcon size={10}/><i style:background={pin.targetHex}></i><button class="text-button" aria-label={`Remove correction ${i + 1}`} disabled={busy} onclick={() => { pins = pins.filter((_, index) => index !== i); dirty = true; }}><XIcon size={12}/></button></span>{/each}<button class="text-button" disabled={busy} onclick={() => { pins = []; dirty = true; }}>Clear all</button><span>Applies to similar colours across the model.</span></div>{/if}</section>
      <section class="print-panel"><div class="print-top"><div class="print-title"><span class="print-icon">{#if project?.printCurrent && !dirty}<CircleCheckIcon size={22}/>{:else}<FileBoxIcon size={22}/>{/if}</span><div><p class="eyebrow">FROM PREVIEW TO PRINT</p><h2>{project?.printCurrent && !dirty ? 'Your print project is ready.' : 'Make something worth holding.'}</h2><p>{project?.printCurrent && !dirty ? 'Native INDX project · reopened and sliced in PrusaSlicer alpha13' : 'Create a native INDX project, checked in PrusaSlicer before saving.'}</p></div></div><button class="primary export-button" disabled={!project || busy} onclick={() => runJob('build')}><FileBoxIcon size={16}/> Save print revision<ArrowRightIcon size={16}/></button></div>
      {#if project?.validation}<div class="print-metrics"><div><span><Clock3Icon size={12}/>{project.printCurrent && !dirty ? 'Estimated print time' : 'Previous print time'}</span><strong>{project.validation.estimatedPrintTime || project.validation.printTime?.[0]?.split(' = ')[1] || 'See report'}</strong></div><div><span>Filament</span><strong>{project.validation.filamentGrams?.toFixed(2) || '—'} <small>g</small></strong></div><div><span>Tool changes</span><strong>{project.validation.toolChangeCount ?? '—'}</strong></div><a class="secondary download" href={`/api/download?name=${encodeURIComponent(project.name)}`}><ArrowDownToLineIcon size={15}/>{project.printCurrent && !dirty ? 'Download 3MF' : 'Previous 3MF'}</a></div><details class="diagnostics"><summary><span>Slice diagnostics <span class="notice-count">{project.validation.validation.warnings.length}</span></span><ChevronDownIcon size={13}/></summary><p>Not physically tested. Inspect fine colour regions before printing.</p>{#each project.validation.validation.warnings as warning}<p>{warning}</p>{/each}</details>{:else}<p class="print-note">Print time, filament use and tool changes appear after validation.</p>{/if}
      </section>
      <footer class="workspace-footer"><span><Link2Icon size={11}/> One workspace, in browser and chat.</span><span>PLA colour · Supports reviewed separately</span></footer>
    </main>
  </div>
</div>
