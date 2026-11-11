// Offline browser-behavior regression checks. No network, Supabase, or secrets required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const portalScript = fs.readFileSync(path.join(root, 'client/scripts/portal.js'), 'utf8');
const loginScript = fs.readFileSync(path.join(root, 'client/scripts/login.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;});return {promise,resolve,reject}; }
function mockNode() {return {innerHTML:'',value:'',textContent:'',dataset:{},style:{},onclick:null,onsubmit:null,classList:{add(){},remove(){},toggle(){}},appendChild(){},addEventListener(){}};}
function createDocument(){
  const nodes = new Map();
  const get = id => {if(!nodes.has(id))nodes.set(id,mockNode());return nodes.get(id);};
  const document = {
    querySelector(sel){
      const id = sel.startsWith('#') ? sel.substring(1) : '';
      const content = get('portalContent').innerHTML;
      if (['dashboardData','applyPeriod','periodSelect','periodDate','staffForm'].includes(id)) {
        if(!content.includes(`id="${id}"`))return null;
      }
      return get(id || sel);
    },
    querySelectorAll(){return [];},
    createElement(){return mockNode();},
    body:{classList:{add(){},remove(){}}},
    addEventListener(){},
  };
  return {document,get};
}
function makePortalAPI(overrides = {}){
  const dashboard = {income:0,salesCount:0,grossProfit:0,cashOutflow:0,operatingResult:0,lowStockCount:0,
    pendingPrescriptionCount:0,openConsultationCount:0,cogs:0,stockPurchases:0,operatingExpenses:0,wages:0,
    activity:[],orders:[]};
  return {ready: async()=>true,me:async()=>({profile:{id:'admin-id',role:'admin',full_name:'Admin',email:'admin@example.invalid'}}),
    portalBootstrap:async()=>({products:[],branches:[],categories:[],manufacturers:[],suppliers:[]}),
    adminDashboard:async()=>dashboard,staff:async()=>[],portalBadges:async()=>({}),notifications:async()=>[],
    ...overrides};
}
function makePortalContext(API){
  const {document,get}=createDocument();
  const calls=[];
  const context=vm.createContext({document,API,console,FormData:class {},setTimeout,location:{replace:path=>calls.push(path)},
    window:{lucide:{createIcons(){}},addEventListener(){}},});
  vm.runInContext(portalScript,context);
  return {context,get,calls};
}
async function testAdminLandsOnDashboard(){
  const {context,get,calls}=makePortalContext(makePortalAPI());
  await vm.runInContext('sessionStart()',context);
  await tick();await tick();
  assert.deepEqual(calls,[]);
  assert.equal(get('pageTitle').textContent,'Dashboard');
  assert.match(get('portalContent').innerHTML,/Financial period/);
  assert.equal(get('roleLabel').textContent,'Admin');
}
async function testStaffRemainsVisibleAfterStaleDashboardResponse(){
  const pending=deferred();
  const {context,get}=makePortalContext(makePortalAPI({adminDashboard:()=>pending.promise}));
  vm.runInContext("portalState.user={profile:{role:'admin'}}",context);
  const first=vm.runInContext("navigate('overview')",context);
  const second=vm.runInContext("navigate('staff')",context);
  await second;
  assert.match(get('portalContent').innerHTML,/Create pharmacy staff account/);
  assert.match(get('portalContent').innerHTML,/name="password"/);
  assert.match(get('portalContent').innerHTML,/name="confirm_password"/);
  assert.doesNotMatch(get('portalContent').innerHTML,/Send staff invitation/);
  pending.resolve({income:0,salesCount:0,grossProfit:0,cashOutflow:0,operatingResult:0,
    lowStockCount:0,pendingPrescriptionCount:0,openConsultationCount:0,cogs:0,
    stockPurchases:0,operatingExpenses:0,wages:0,activity:[],orders:[]});
  await first;
  assert.equal(get('pageTitle').textContent,'Staff Accounts');
  assert.match(get('portalContent').innerHTML,/Create pharmacy staff account/);
  assert.doesNotMatch(get('portalContent').innerHTML,/Could not load this section/);
}
async function testStaffRemainsVisibleAfterStaleDashboardError(){
  const pending=deferred();
  const {context,get}=makePortalContext(makePortalAPI({adminDashboard:()=>pending.promise}));
  vm.runInContext("portalState.user={profile:{role:'admin'}}",context);
  const first=vm.runInContext("navigate('overview')",context);
  const second=vm.runInContext("navigate('staff')",context);
  await second;
  pending.reject(new Error('Old dashboard error'));
  await first;
  assert.equal(get('pageTitle').textContent,'Staff Accounts');
  assert.match(get('portalContent').innerHTML,/Create pharmacy staff account/);
}
async function testLateStaffResponseDoesNotOverwriteDashboard(){
  const pending=deferred();
  const {context,get}=makePortalContext(makePortalAPI({staff:()=>pending.promise}));
  vm.runInContext("portalState.user={profile:{role:'admin'}}",context);
  const first=vm.runInContext("navigate('staff')",context);
  const second=vm.runInContext("navigate('overview')",context);
  await second;
  pending.resolve([]);
  await first;
  assert.equal(get('pageTitle').textContent,'Dashboard');
  assert.match(get('portalContent').innerHTML,/Financial period/);
  assert.doesNotMatch(get('portalContent').innerHTML,/Create pharmacy staff account/);
}
function testRoleRouting(){
  const {document}=createDocument();
  const fakeSession={getItem(){return null},setItem(){},removeItem(){}};
  const api={};
  const location={search:'?next=%2F',hash:'',pathname:'/login'};
  const context=vm.createContext({document,window:{lucide:{createIcons(){}},addEventListener(){}},location,API:api,
    sessionStorage:fakeSession,history:{replaceState(){}},URLSearchParams,console});
  const exposed=loginScript.replace(/\}\)\(\);\s*$/, 'window.__routeForRole = routeForRole;\n})();');
  assert.notEqual(exposed,loginScript);
  vm.runInContext(exposed,context);
  const roleFor = context.window.__routeForRole;
  for(const role of ['admin','ADMIN','pharmacist','merchandiser','delivery']){
    assert.equal(roleFor(role),'/workspace',`staff role ${role} did not reach workspace`);
  }
  assert.equal(roleFor('customer'),'/');
}
(async()=>{
  await testAdminLandsOnDashboard();
  await testStaffRemainsVisibleAfterStaleDashboardResponse();
  await testStaffRemainsVisibleAfterStaleDashboardError();
  await testLateStaffResponseDoesNotOverwriteDashboard();
  testRoleRouting();
  console.log('PASS: Admin dashboard initial view');
  console.log('PASS: Switching Dashboard -> Staff Accounts during delayed dashboard response');
  console.log('PASS: Switching Dashboard -> Staff Accounts during late dashboard error');
  console.log('PASS: Switching Staff Accounts -> Dashboard during delayed staff response');
  console.log('PASS: Unified sign-in routes Admin and staff to /workspace');
})().catch(err=>{console.error(err);process.exitCode=1});
