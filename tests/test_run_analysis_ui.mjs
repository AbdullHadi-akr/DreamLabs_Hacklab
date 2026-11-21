// Run with: node tests/test_run_analysis_ui.mjs
import { readFile } from "node:fs/promises";
import { Script } from "node:vm";

const files = ["dashboard/static/lib/api.js", "dashboard/static/lib/log_panel.js",
  "dashboard/extensions/test_suite/run_analysis.js", "dashboard/extensions/test_suite/panel.js"];
const sources = await Promise.all(files.map((file) => readFile(new URL("../" + file, import.meta.url), "utf8")));
const css = await readFile(new URL("../dashboard/extensions/test_suite/panel.css", import.meta.url), "utf8");
await verifyRunAnalysis(sources, css, Script);
console.log("Run selector, lazy snapshots, comparison, history and large campaign checks passed");

async function verifyRunAnalysis(sources, css, Script) {
  const fixture = `
class FakeElement {
  constructor(tag) { this.tag=tag; this.children=[]; this.attrs={}; this.events={}; this.value=""; this.open=false;
    this.classList={toggle(){}}; }
  setAttribute(key,value) { this.attrs[key]=String(value); if(key==="id")this.id=value; if(key==="value")this.value=String(value); if(key==="open")this.open=true; }
  addEventListener(name,fn) { this.events[name]=fn; }
  removeEventListener(name,fn) { if(this.events[name]===fn)delete this.events[name]; }
  append(...nodes) { for(const node of nodes) {node.parentElement=this; this.children.push(node);} }
  replaceChildren(...nodes) { this.children=[]; this.append(...nodes); }
  get firstChild() { return this.children[0]; }
  get textContent() { return this.children.map((child)=>child.textContent).join(""); }
  set textContent(text) { this.children=[{textContent:String(text)}]; }
  setCustomValidity() {}
  focus() {}
  scrollIntoView() {}
}
const nodes=new Map();
globalThis.Node=FakeElement;
globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,new FakeElement(id));return nodes.get(id);},
  createElement(tag){return new FakeElement(tag);}, createTextNode(text){return {textContent:text};},
  querySelector(){return new FakeElement("layout");}};
globalThis.window={setInterval(){}};
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
Object.assign(reports.large.trials[0],{task_success:true,task_duration_seconds:5.4,evaluation_evidence:{object:"apple",target:"bowl",best_planar_distance_m:.01},
  snapshots:[{kind:"final",simulation_time:4}]});
Object.assign(reports.large.trials[1],{task_success:false,failure_category:"PICKUP_FAILED",failure_reason:"Exact run 2 evaluation",
  termination_reason:"task_deadline",execution_status:"timed_out",task_duration_seconds:17,
  last_verified_stage:"Gripper contact",api_request_count:4,snapshots:[{kind:"contact",simulation_time:9}],
  api_events:[{error:"run 2 request error"}],evaluation_evidence:{object:"banana",target:"plate",best_planar_distance_m:.17}});
const reads=[];
const coreEvents={};
const robustnessRoot=new FakeElement("div");
const robustness={state:"running", mode:"adaptive", done:2, total:12, started:Date.now()/1000,
  config:{task:"banana on plate",dry_run:false}};
globalThis.fetch=async()=>({ok:true,text:async()=>JSON.stringify(robustness)});
const api={ui:{h,toast(){}},on(){},onCore(name,fn){coreEvents[name]=fn;},
  workspace:{extensions:()=>[{id:"robustness",root:robustnessRoot}]},async get(url){ reads.push(url);
  if(url==="/history")return Object.values(reports).map((r)=>({id:r.id,state:r.state,created:1,config:r.config}));
  if(url.endsWith("/actions/2"))return [{reply:"run 2 action"}];
  return reports[url.split("/").at(-1)]; }};
(async()=>{
  await mount(document.getElementById("config"),api);
  document.getElementById("workspace-test-suite").events.click();
  await new Promise((resolve)=>setTimeout(resolve,0));
  const monitor=document.getElementById("test-suite-monitor");
  assert(monitor.textContent.includes("Breaking Point · 2/12 trials completed"),"right monitor reads a running Breaking Point campaign");
  coreEvents["ext.robustness.progress"]({...robustness, done:3});
  assert(monitor.textContent.includes("3/12 trials completed"),"right monitor follows progress events");
  coreEvents["ext.robustness.progress"]({...robustness, state:"done"});
  assert(monitor.textContent.includes("No campaign running"),"right monitor clears completed campaign");
  robustnessRoot.events["suite-campaign-started"]({detail:{...robustness, done:0}});
  assert(monitor.textContent.includes("0/12 trials completed"),"right monitor shows a new campaign immediately");
  const results=document.getElementById("test-suite-results");
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
  tabs[0].events.click();
  assert(panel.textContent.includes("prompt-1") && !panel.textContent.includes("Exact run 2"),"switching back restores run 1");
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
})()
`;
  const strip = css.match(/\.suite-run-strip\s*\{([^}]*)\}/)?.[1] || "";
  if (!/overflow-x:\s*auto/.test(strip) || !/flex-wrap:\s*nowrap/.test(strip)) throw Error("Run strip must scroll without wrapping");
  const source = sources.map((text) => text.replace(/^import.*\n/gm, "").replace(/^export /gm, "")).join("\n");
  await new Script(source + "\n" + fixture).runInNewContext({setTimeout});
}
