// Run with: node tests/test_run_analysis_ui.mjs
import { readFile } from "node:fs/promises";
import { Script } from "node:vm";

const files = ["dashboard/static/lib/api.js", "dashboard/static/lib/log_panel.js",
  "dashboard/extensions/test_suite/fork_panel.js",
  "dashboard/extensions/test_suite/run_analysis.js", "dashboard/extensions/test_suite/panel.js"];
const sources = await Promise.all(files.map((file) => readFile(new URL("../" + file, import.meta.url), "utf8")));
const css = await readFile(new URL("../dashboard/extensions/test_suite/panel.css", import.meta.url), "utf8");
await verifyRunAnalysis(sources, css, Script);
verifyResponseChart(await readFile(new URL("../dashboard/static/app.js", import.meta.url), "utf8"), Script);
console.log("Run reports, notifications, print recovery and response chart checks passed");

async function verifyRunAnalysis(sources, css, Script) {
  const fixture = `
class FakeElement {
  constructor(tag) { this.tag=tag; this.children=[]; this.attrs={}; this.events={}; this.value=""; this.open=false;
    this.classList={toggle(){}}; }
  setAttribute(key,value) { this.attrs[key]=String(value); if(key==="id")this.id=value; if(key==="value")this.value=String(value); if(key==="open")this.open=true; }
  addEventListener(name,fn) { this.events[name]=fn; }
  dispatchEvent(event) { return this.events[event.type]?.(event); }
  removeEventListener(name,fn) { if(this.events[name]===fn)delete this.events[name]; }
  append(...nodes) { for(const node of nodes) {node.parentElement=this; this.children.push(node);} }
  replaceChildren(...nodes) { this.children=[]; this.append(...nodes); }
  get firstChild() { return this.children[0]; }
  get textContent() { return this.children.map((child)=>child.textContent).join(""); }
  set textContent(text) { this.children=[{textContent:String(text)}]; }
  setCustomValidity() {}
  focus() {}
  scrollIntoView() {}
  remove() { this.parentElement.children=this.parentElement.children.filter((child)=>child!==this); }
}
const nodes=new Map();
globalThis.Node=FakeElement;
globalThis.document={addEventListener(){},getElementById(id){if(!nodes.has(id))nodes.set(id,new FakeElement(id));return nodes.get(id);},
  createElement(tag){return new FakeElement(tag);}, createTextNode(text){return {textContent:text};},
  querySelector(){return new FakeElement("layout");}};
globalThis.Event=class {constructor(type){this.type=type;}};
globalThis.CustomEvent=class extends Event {constructor(type, options){super(type);this.detail=options.detail;}};
globalThis.window=new FakeElement("window");
window.setInterval=()=>{};
window.clearTimeout=()=>{};
let printed=0;
window.print=()=>{printed++;};
function assert(condition, message) { if(!condition) throw Error(message); }
function descendants(node, predicate) {
  if(!(node instanceof FakeElement))return [];
  return [...(predicate(node)?[node]:[]),...node.children.flatMap((child)=>descendants(child,predicate))];
}
function find(node,predicate){ return descendants(node,predicate)[0]; }
const run=(number, properties={})=>({number, case:{prompt:"prompt-"+number}, task_success:null,
  execution_status:"completed", termination_reason:"done", safety_status:"not_evaluated", ...properties});
const report=(id,trials)=>({id,state:"done",total:trials.length,config:{mode:"quick",prompt:"campaign-"+id},
  trials,stats:{trials:trials.length,successes:0,failures:0,unevaluated:0,evaluated:0,requests:0,safety:{},durations_by_status:{}},
  execution:{},reasons:{},conditions:{},logs:[]});
const reports={
  large:report("large",Array.from({length:100},(_,i)=>run(i+1))),
  historic:report("historic",[run(1,{snapshot_available:true})])
};
reports.historic.stats.unevaluated=1;
Object.assign(reports.large.trials[0],{task_success:true,task_duration_seconds:5.4,evaluation_evidence:{object:"apple",target:"bowl",best_planar_distance_m:.01},
  snapshots:[{kind:"final",simulation_time:4}],checkpoint:{id:"checkpoint-one",simulation_time:3,scripted:true}});
Object.assign(reports.large.trials[1],{task_success:false,failure_category:"PICKUP_FAILED",failure_reason:"Exact run 2 evaluation",
  termination_reason:"task_deadline",execution_status:"timed_out",task_duration_seconds:17,
  last_verified_stage:"Gripper contact",api_request_count:4,snapshots:[{kind:"contact",simulation_time:9}],
  api_events:[{error:"run 2 request error"}],evaluation_evidence:{object:"banana",target:"plate",best_planar_distance_m:.17}});
const reads=[];
const coreEvents={};
const suiteEvents={};
const robustnessRoot=new FakeElement("div");
const robustness={id:"robust-campaign",rows:[],state:"running", mode:"adaptive", done:2, total:12, started:Date.now()/1000,
  config:{task:"banana on plate",dry_run:false}};
globalThis.fetch=async(url,options)=>{assert(options.method==="GET","print recovery must not mutate campaigns");
  return {ok:true,text:async()=>JSON.stringify(robustness)};};
const api={ui:{h,toast(){}},on(name,fn){(suiteEvents[name]||=[]).push(fn);},onCore(name,fn){coreEvents[name]=fn;},
  workspace:{extensions:()=>[{id:"robustness",root:robustnessRoot,suite_modes:[{id:"random",title:"Perturbation Mix",subtitle:"Scripted"}]}]},
  async get(url){ reads.push(url);
  if(url==="/history")return Object.values(reports).map((r)=>({id:r.id,state:r.state,created:1,config:r.config}));
  if(url.endsWith("/actions/2"))return [{reply:"run 2 action"}];
  if(url.endsWith("/forks/1/quote"))return {api_request_limit:0,max_cost_usd:0};
  if(url.endsWith("/forks/1"))return [{id:"comparison-one",state:"done",branches:{
    baseline:{status:"complete",outcome:false,requests:0,cost_usd:0},
    guarded:{status:"complete",outcome:true,requests:0,cost_usd:0}}}];
  return reports[url.split("/").at(-1)]; }};
(async()=>{
  await mount(document.getElementById("config"),api);
  document.getElementById("workspace-test-suite").events.click();
  await new Promise((resolve)=>setTimeout(resolve,0));
  const monitor=document.getElementById("test-suite-monitor");
  assert(monitor.textContent.includes("Breaking Point · Trial 3 of 12"),"right monitor reads a running Breaking Point campaign");
  coreEvents["ext.robustness.progress"]({...robustness, done:3});
  assert(monitor.textContent.includes("Trial 4 of 12"),"right monitor follows progress events");
  coreEvents["ext.robustness.progress"]({...robustness, id:"old-campaign", state:"done"});
  assert(monitor.textContent.includes("No campaign running"),"right monitor clears completed campaign");
  robustnessRoot.events["suite-campaign-started"]({detail:{...robustness, done:0}});
  assert(monitor.textContent.includes("Trial 1 of 12"),"right monitor shows a new campaign immediately");
  const results=document.getElementById("test-suite-results");
  const buildTab=document.getElementById("suite-build-tab");
  const reportTab=document.getElementById("suite-report-tab");
  const preview=document.getElementById("simulation-preview");
  assert(results.hidden && preview.open,"Build keeps results out of the monitoring layout");
  reportTab.events.click();
  assert(!results.hidden && !preview.open,"Report opens above a collapsed simulation preview");
  const monitorActions=find(monitor,(node)=>node.className==="suite-actions monitor-actions");
  assert(!monitorActions.hidden && monitorActions.children[1].hidden,"Report keeps the active robustness Stop control available");
  const strip=find(results,(node)=>node.attrs.role==="tablist");
  const tabs=descendants(strip,(node)=>node.attrs.role==="tab");
  const panel=find(results,(node)=>node.attrs.role==="tabpanel");
  assert(tabs.length===100 && strip.className==="suite-run-strip","100 runs must use one scroll strip");
  assert(tabs[0].attrs["aria-selected"]==="true" && panel.textContent.includes("Run 1 · Success"),"default success run");
  tabs[1].events.click();
  assert(panel.textContent.includes("Exact run 2 evaluation") && panel.textContent.includes("prompt-2") &&
    !panel.textContent.includes("prompt-1") && panel.textContent.includes("run 2 request error"),"run 2 details exact");
  assert(tabs[1].attrs["aria-selected"]==="true" && tabs[0].attrs["aria-selected"]==="false","selected tab semantics");
  assert(descendants(panel,(node)=>node.tag==="img").length===0,"snapshot lazy load");
  const snapshot=find(panel,(node)=>node.tag==="details" && node.firstChild.textContent.startsWith("Snapshot timeline"));
  snapshot.open=true; snapshot.events.toggle();
  assert(find(snapshot,(node)=>node.tag==="img").attrs.src.endsWith("/reports/large/snapshot/2/contact"),"run 2 snapshot URL");
  const actions=find(panel,(node)=>node.tag==="details" && node.firstChild.textContent==="Dream-1 action replies");
  actions.open=true; await actions.events.toggle();
  assert(actions.textContent.includes("run 2 action") && reads.includes("/reports/large/actions/2"),"run 2 action endpoint");
  const runButton=find(results,(node)=>node.attrs["aria-label"]==="Inspect run 2");
  assert(runButton.attrs["aria-pressed"]==="true","run table follows selected run");
  buildTab.events.click();
  reportTab.events.click();
  assert(tabs[1].attrs["aria-selected"]==="true" && panel.textContent.includes("prompt-2"),"Build and Report preserve selection");
  tabs[0].events.click();
  assert(panel.textContent.includes("prompt-1") && !panel.textContent.includes("Exact run 2"),"switching back restores run 1");
  const fork=find(panel,(node)=>node.tag==="details"&&node.firstChild.textContent==="Fork here");
  fork.isConnected=true;
  fork.open=true;
  fork.events.toggle();
  await new Promise((resolve)=>setTimeout(resolve,0));
  assert(fork.textContent.includes("Added API requests: 0")&&!fork.textContent.includes("undefined"),"fork report omits missing error text");
  assert(reads.filter((url)=>url==="/reports/large").length===1,"run changes are local");
  const compare=find(results,(node)=>node.tag==="details"&&node.firstChild.textContent==="Compare Runs");
  const selectors=descendants(compare,(node)=>node.tag==="select");
  selectors[0].value="2";selectors[1].value="3";selectors[1].events.change();
  assert(compare.textContent.includes("pickup failed") && compare.textContent.includes("17.0 s") &&
    !compare.textContent.includes("5.4 s"),"compare the selected run IDs only");
  const history=find(results,(node)=>node.attrs["aria-label"]==="Campaign history");
  history.value="historic"; history.events.change();
  await new Promise((resolve)=>setTimeout(resolve,0));
  const historic=find(results,(node)=>node.attrs.role==="tabpanel");
  assert(historic.textContent.includes("No time-series target measurements were recorded") &&
    historic.textContent.includes("Safety coverage unavailable"),"historical missing telemetry");
  const legacy=find(historic,(node)=>node.tag==="details"&&node.firstChild.textContent.startsWith("Snapshot timeline"));
  legacy.open=true;legacy.events.toggle();
  assert(find(legacy,(node)=>node.tag==="img").attrs.src.endsWith("/reports/historic/snapshot/1"),"legacy snapshot URL");

  for(const listener of suiteEvents.ended) listener({id:"historic",name:"campaign-historic",state:"done",total:1,stats:reports.historic.stats},{t:Date.now()/1000});
  const notice=document.getElementById("campaign-notices").children[0];
  assert(notice.textContent.includes("campaign-historic"),"completion banner names the completed campaign");
  buildTab.events.click();
  const modeSelect=find(document.getElementById("config"),(node)=>node.attrs["aria-label"]==="Test type");
  assert(find(modeSelect,(node)=>node.tag==="option"&&node.attrs.value==="robustness:random"),"Perturbation Mix remains available");
  modeSelect.value="robustness:random";
  modeSelect.onchange();
  Object.assign(robustness,{mode:"random",done:2,total:4});
  robustnessRoot.events["suite-campaign-started"]({detail:robustness});
  reportTab.events.click();
  const reportKind=find(results,(node)=>node.attrs["aria-label"]==="Report type");
  reportKind.value="robustness"; reportKind.events.change();
  assert(find(results,(node)=>node.id==="robustness-wide-report").hidden===false,"external report type shown");
  await find(notice,(node)=>node.tag==="button" && node.textContent==="View report").events.click();
  assert(find(results,(node)=>node.id==="robustness-wide-report").hidden===true &&
    results.textContent.includes("1 of 1 runs recorded") && results.textContent.includes("1 unevaluated"),"old toast opens the exact regular report");
  assert(monitor.textContent.includes("Random Mix · Trial 3 of 4"),"old toast leaves the mix running");
  assert(find(results,(node)=>node.attrs.href?.endsWith("/reports/historic/export/csv")),"Export menu uses the selected campaign");
  find(results,(node)=>node.tag==="button" && node.textContent==="Print / PDF").events.click();
  assert(printed===1,"Print / PDF invokes browser preview");
  const before=reads.filter((url)=>url==="/reports/historic").length;
  Object.assign(robustness,{mode:"random",done:3,total:4});
  window.events.afterprint();
  window.events.focus();
  await new Promise((resolve)=>setTimeout(resolve,0));
  assert(reads.filter((url)=>url==="/reports/historic").length===before+1,"preview close re-reads the same report once");
  assert(monitor.textContent.includes("Random Mix · Trial 4 of 4"),"preview close re-reads authoritative mix progress");
  coreEvents["ext.robustness.progress"]({...robustness,state:"done",done:4});
  assert(monitor.textContent.includes("No campaign running"),"recovered monitor handles completion");
})()
`;
  const strip = css.match(/\.suite-run-strip\s*\{([^}]*)\}/)?.[1] || "";
  if (!/overflow-x:\s*auto/.test(strip) || !/flex-wrap:\s*nowrap/.test(strip)) throw Error("Run strip must scroll without wrapping");
  const source = sources.map((text) => text.replace(/^import.*\n/gm, "").replace(/^export /gm, "")).join("\n");
  await new Script(source + "\n" + fixture).runInNewContext({setTimeout});
}

function verifyResponseChart(source, Script) {
  const chart = source.slice(source.indexOf("let chartRun ="), source.indexOf("// ---------------- Events"));
  new Script(chart + `
    setChartRun({id:1,model:"mocked Dream-1",rtts_s:[.2,.4]});
    if (scope.textContent!=="Run #1 · API RTT" || !text.at(-1).includes("avg 0.30 s")) throw Error("API samples missing");
    setChartRun({id:2,model:"offline",rtts_s:[]});
    if (scope.textContent!=="Run #2 · Offline" || text.at(-1)!=="Offline run · no API requests") throw Error("offline chart retained API samples");
  `).runInNewContext(chartContext());
}

function chartContext() {
  const text = [];
  const scope = {};
  const context = new Proxy({fillText: (value) => text.push(value), createLinearGradient: () => ({addColorStop(){}})}, {
    get: (target, key) => target[key] || (() => {}),
  });
  return { text, scope, window:{}, document:{documentElement:{}}, getComputedStyle:()=>({getPropertyValue:()=>""}),
    $:(id)=>id==="rtt-scope"?scope:{clientWidth:300,clientHeight:90,getContext:()=>context} };
}
