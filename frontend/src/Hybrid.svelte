<script lang="ts">
  import { onMount } from 'svelte';
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
    <div class="brand"><span class="brand-mark" aria-hidden="true">▦</span><div><strong>INDX <span>Colour Studio</span></strong><small>DitherForge · browser + chat</small></div></div>
    <div class="header-right"><span class="local-badge"><i></i> Local on your Mac</span><span class="machine">CORE One · 8 × 0.4 HF</span></div>
  </header>

  <div class="studio-layout">
    <aside class="studio-sidebar" aria-label="Project controls">
      <section class="control-section">
        <h2>Workspace</h2>
        <label for="project">Project</label>
        <div class="project-select"><select id="project" value={selected} disabled={busy} onchange={async e => { const select = e.currentTarget; await switchProject(select.value); select.value = selected; }}><option value="" disabled>Choose a project</option>{#each projects as name}<option>{name}</option>{/each}</select><button class="icon-button" aria-label="Reload project from disk" disabled={!project || busy} onclick={() => loadProject(selected)}>↻</button></div>
        <details class="import-panel"><summary>＋ Import a model</summary><label for="new-project">New project name</label><input id="new-project" bind:value={projectName} placeholder="Use model filename" disabled={busy}/><label class:disabled={busy} class="file-button" for="model-file">{uploading ? 'Copying model…' : 'Choose model file'}</label><input id="model-file" class="visually-hidden" type="file" accept=".glb,.3mf,.stl,.obj,.dae,.zip" disabled={busy} onchange={importModel}/><p>GLB, 3MF, STL, OBJ or model ZIP. Saved in your 3D print folder.</p></details>
      </section>

      <section class="control-section">
        <div class="section-heading"><h2>Tool colours</h2><span>{activeTools} / 8 selected</span></div>
        <p class="help-text">Choose the spools you intend to load.</p>
        <div class="tool-list">
          {#each tools as tool (tool.tool)}
            <div class:tool-inactive={tool.role !== 'color'} class="tool-row">
              <label class="tool-check" title={tool.type === 'PETG' ? 'PETG stays out of the PLA colour mix' : 'Include in colour palette'}><input type="checkbox" aria-label={`Use tool ${tool.tool} for colour`} checked={tool.role === 'color'} disabled={busy || tool.type === 'PETG'} onchange={() => toggleTool(tool)}/><span>T{tool.tool}</span></label>
              <input type="color" aria-label={`Tool ${tool.tool} colour`} value={tool.color || '#808080'} disabled={busy || tool.role !== 'color'} oninput={e => { tool.color = e.currentTarget.value; dirty = true; }}/>
              <div class="spool-fields"><input class="spool-name" aria-label={`Tool ${tool.tool} spool name`} value={tool.label || ''} placeholder="Assign a spool" disabled={busy} oninput={e => { tool.label = e.currentTarget.value; dirty = true; }}/><select aria-label={`Tool ${tool.tool} material`} value={tool.type || ''} disabled={busy} onchange={e => { tool.type = e.currentTarget.value; if (tool.type === 'PETG') tool.role = 'support'; dirty = true; }}><option value="">Unassigned</option><option>PLA</option><option>PETG</option></select>{#if tool.type === 'PETG'}<span class="reserved">Reserved</span>{/if}</div>
            </div>
          {/each}
        </div>
      </section>

      <section class="control-section" aria-label="Print and colour settings">
        <h2>Print & colour</h2>
        <div class="two-fields"><label>Longest side <div class="unit-input"><input aria-label="Longest side in millimetres" type="number" min="1" max="300" bind:value={options.sizeValue} disabled={busy} oninput={() => dirty = true}/><span>mm</span></div></label><label>Layer height<select aria-label="Layer height" bind:value={options.layerHeight} disabled={busy} onchange={() => dirty = true}>{#each layerChoices as h}<option value={h}>{h.toFixed(2)} mm</option>{/each}</select></label></div>
        <label>Dither pattern<select aria-label="Dither pattern" bind:value={options.dither} disabled={busy} onchange={() => dirty = true}><option value="dlc-d30-p7">Dizzy · balanced</option><option value="riemersma">Riemersma</option><option value="floyd-steinberg">Floyd–Steinberg</option><option value="bn-adapt-5">Blue noise</option><option value="none">Solid colours only</option></select></label>
        <label class="range-label">Colour cell size <output>{options.upperLayerXYScale.toFixed(2)}×</output><input aria-label="Colour cell size" type="range" min="1" max="4" step="0.05" bind:value={options.upperLayerXYScale} disabled={busy} oninput={() => dirty = true}/></label><p class="help-text">Larger cells trade fine colour detail for fewer small regions.</p>
        <details><summary>Fine tuning</summary>
          {#each ['brightness', 'contrast', 'saturation'] as key}<label class="range-label">{key[0].toUpperCase() + key.slice(1)}<output>{options[key as 'brightness' | 'contrast' | 'saturation']}</output><input aria-label={key} type="range" min="-100" max="100" value={options[key as 'brightness' | 'contrast' | 'saturation']} disabled={busy} oninput={e => { options[key as 'brightness' | 'contrast' | 'saturation'] = Number(e.currentTarget.value); dirty = true; }}/></label>{/each}
          <label class="range-label">Reduce near-solid speckle<output>{options.colorSnap}</output><input aria-label="Reduce near-solid speckle" type="range" min="0" max="50" bind:value={options.colorSnap} disabled={busy} oninput={() => dirty = true}/></label>
          <label>Mesh repair<select aria-label="Mesh repair" bind:value={options.meshRepair} disabled={busy} onchange={() => dirty = true}><option value="none">Use original geometry</option><option value="fwn">Winding-number remesh</option><option value="alphawrap">Alpha wrap</option></select></label>
        </details>
      </section>
      <div class="sidebar-actions"><button class="secondary" disabled={!project || !dirty || busy} onclick={saveOnly}>Save settings</button><button class="primary" disabled={!project || busy} onclick={() => runJob('preview')}>{busy ? 'Working…' : 'Update preview'} <span>↗</span></button></div>
    </aside>

    <main class="studio-main">
      <div class="workspace-heading"><div><p class="eyebrow">COLOUR WORKSPACE</p><h1>{project?.name || 'Make your next colour print'}</h1><p>{project ? project.sourceName : 'Import a textured model to start.'}</p></div><button class="secondary" disabled={!project} onclick={resetView}>Reset view</button></div>
      {#if error}<div class="message error" role="alert">{error}</div>{/if}
      {#if notice}<div class="message success" role="status">{notice}</div>{/if}
      {#if busy}<div class="job-status" role="status"><span class="spinner"></span><strong>{job?.kind === 'build' ? 'Validating your print project' : uploading ? 'Importing model' : 'Preparing your preview'}</strong><span>{stage}</span></div>{/if}

      <div class="viewer-grid">
        <section class="viewer-panel" aria-label="Source model viewer"><div class="viewer-heading"><h2>{options.brightness || options.contrast || options.saturation || pins.length ? 'Adjusted source' : 'Source model'}</h2><span>REFERENCE</span></div><div class="viewer-canvas">{#key viewEpoch}<ModelViewer meshUrl={inputUrl} label="Source model" viewerId="hybrid-input" {camera} brightness={options.brightness} contrast={options.contrast} saturation={options.saturation} warpPins={pins.map(p => ({sourceHex:p.sourceHex,targetHex:p.targetHex,sigma:p.sigma}))} {pickMode} onColorPick={hex => { sampledColor = hex; pickMode = false; }} progressActive={false}/>{/key}{#if !inputUrl}<div class="viewer-empty">{busy ? 'Loading source geometry…' : 'Your model appears here'}</div>{/if}</div><div class="viewer-footer">Drag to rotate · Scroll to zoom · Right-drag to pan</div></section>
        <section class="viewer-panel" aria-label="Dithered model viewer"><div class="viewer-heading"><h2>Dithered preview</h2><span class:needs-update={previewStale}>{previewStale ? 'NEEDS UPDATE' : 'FILAMENT COLOURS'}</span></div><div class="viewer-canvas">{#key viewEpoch}<ModelViewer meshUrl={outputUrl} label="Dithered model" viewerId="hybrid-output" {camera} progressActive={false}/>{/key}{#if !outputUrl}<div class="viewer-empty">{busy ? 'Building printable colour regions…' : 'Generate a preview to compare'}</div>{/if}</div><div class="viewer-footer">Cameras linked · Appearance is uncalibrated</div></section>
      </div>

      <section class="correction-panel"><div><h2>Correct a colour</h2><p>Sample the source, choose a target, then update the preview.</p></div><button class:active={pickMode} class="secondary" disabled={!inputUrl || busy} onclick={() => pickMode = !pickMode}>{pickMode ? 'Click the source model…' : '⌖ Pick on model'}</button><input aria-label="Source correction colour" type="color" bind:value={sampledColor}/><span>→</span><input aria-label="Target correction colour" type="color" bind:value={correctionColor}/><button class="secondary" disabled={busy || pins.length >= 8 || !project} onclick={addPin}>Add correction</button>{#if pins.length}<button class="text-button" disabled={busy} onclick={() => { pins = []; dirty = true; }}>Clear {pins.length}</button>{/if}</section>

      <section class="print-panel"><div class="print-top"><div><p class="eyebrow">NATIVE PRUSASLICER PROJECT</p><h2>{project?.printCurrent && !dirty ? 'Validated for these settings' : 'Ready when you are'}</h2><p>Export reopens and slices in alpha13. A previous print is archived after the new revision passes.</p></div><button class="primary export-button" disabled={!project || busy} onclick={() => runJob('build')}>Save print revision <span>↓</span></button></div>
        {#if project?.validation}<div class="print-metrics"><div><span>{project.printCurrent && !dirty ? 'Estimated print time' : 'Last validated print'}</span><strong>{project.validation.estimatedPrintTime || project.validation.printTime?.[0]?.split(' = ')[1] || 'Available in report'}</strong></div><div><span>Filament</span><strong>{project.validation.filamentGrams?.toFixed(2) || '—'} <small>g</small></strong></div><div><span>Tool changes</span><strong>{project.validation.toolChangeCount ?? '—'}</strong></div><a class="secondary download" href={`/api/download?name=${encodeURIComponent(project.name)}`}>{project.printCurrent && !dirty ? 'Download 3MF' : 'Previous 3MF'} ↗</a></div><details class="diagnostics"><summary>Slice diagnostics · {project.validation.validation.warnings.length} notices</summary><p>Not physically tested. Inspect fine colour regions before printing.</p>{#each project.validation.validation.warnings as warning}<p>{warning}</p>{/each}</details>{:else}<p class="print-note">A preview is not a sliced print. Print estimates appear after validation.</p>{/if}
      </section>
      <footer class="workspace-footer"><span>Same project files in browser and chat.</span><span>PLA colour mixing · Supports reviewed separately</span></footer>
    </main>
  </div>
</div>
