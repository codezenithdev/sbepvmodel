"""Browser-side cost conversion retains an original basis and matching receipts."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from sbepv import technoeconomic_cost_year

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js is required')
class CostYearFrontendTests(unittest.TestCase):
    def run_node(self, assertions):
        script = (ROOT / 'frontend/js/06-technoeconomic.js').read_text(encoding='utf-8')
        setup = r"""
const assert=require('node:assert/strict');
const catalog=JSON.parse(require('node:fs').readFileSync('src/sbepv/data/gdp_deflator_2026_09_17.json','utf8'));
const fresh=technoeconomicStandaloneDefaultDraft();
const basis={source_year:2026,applied_year:2026,factor:1,original_costs:technoeconomicCostYearMoney(fresh)};
const close=(a,b)=>assert.ok(Math.abs(Number(a)-Number(b))<=Math.max(1e-12,Math.abs(Number(b))*1e-12),`${a} != ${b}`);
globalThis.technoeconomicApplyingDraft=false;
"""
        result = subprocess.run([shutil.which('node'), '-'], input=script+'\n'+setup+'\n'+assertions,
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_round_trip_uses_originals_and_does_not_change_nonmoney_inputs(self):
        result = self.run_node(r"""
const original=JSON.stringify(fresh);
const converted=technoeconomicCostYearAdjustedDraft(fresh,basis,2022,catalog);
const intermediate=technoeconomicCostYearAdjustedDraft(converted,converted.cost_year_basis,2024,catalog);
const returned=technoeconomicCostYearAdjustedDraft(intermediate,intermediate.cost_year_basis,2026,catalog);
assert.equal(fresh.cost_year,'2026');
assert.equal(converted.cost_year,'2022');
const factor=catalog.years['2022'].value/catalog.years['2026'].value;
close(converted.shared_capex.optimizer_unit_price_usd,37.75*factor);
close(converted.shared_capex.common_capex_wdc.low,1.07*factor);
close(converted.systems.solectria.cost_lines.find(l=>l.key==='Om').distribution.high,13*factor);
close(returned.shared_capex.optimizer_unit_price_usd,37.75);
close(returned.shared_capex.optimizer_installation_wdc.high,.010);
assert.deepEqual(returned.cost_year_basis.original_costs,basis.original_costs);
for(const key of ['n','seed','target_capacity','project_life_years','discount_distribution','degradation_distribution'])assert.deepEqual(converted[key],fresh[key]);
assert.equal(converted.shared_capex.optimizer_count,fresh.shared_capex.optimizer_count);
assert.equal(converted.shared_capex.dc_capacity_mw,fresh.shared_capex.dc_capacity_mw);
assert.equal(JSON.stringify(fresh),original);
const before=technoeconomicAssumptionsCostPreview(fresh),after=technoeconomicAssumptionsCostPreview(converted);
for(const key of Object.keys(before))close(after[key],before[key]*factor);
assert.throws(()=>technoeconomicCostYearAdjustedDraft(fresh,basis,2030,catalog),/No recorded GDP deflator/);
assert.equal(returned.cost_year_basis.receipt.factor,1);
console.log(JSON.stringify({factor,passed:true}));
""")
        self.assertTrue(result['passed'])

    def test_direct_edits_and_family_changes_update_original_equivalents(self):
        self.run_node(r"""
const converted=technoeconomicCostYearAdjustedDraft(fresh,basis,2022,catalog);
technoeconomicCostYearBasis=converted.cost_year_basis;
technoeconomicCostYearDisplayMoney=technoeconomicCostYearMoney(converted);
const originalCommon=JSON.stringify(technoeconomicCostYearBasis.original_costs['shared.common']);
technoeconomicStandaloneDraftSnapshot=()=>converted;
converted.shared_capex.optimizer_unit_price_usd='40';
converted.shared_capex.optimizer_installation_wdc={family:'bounded_normal',low:'.004',high:'.020',mean:'.009',sd:'.002'};
technoeconomicCostYearRecordEdits();
assert.equal(JSON.stringify(technoeconomicCostYearBasis.original_costs['shared.common']),originalCommon);
const returned=technoeconomicCostYearAdjustedDraft(converted,technoeconomicCostYearBasis,2026,catalog);
const inverse=1/converted.cost_year_basis.factor;
close(returned.shared_capex.optimizer_unit_price_usd,40*inverse);
for(const key of ['low','high','mean','sd'])close(returned.shared_capex.optimizer_installation_wdc[key],Number(converted.shared_capex.optimizer_installation_wdc[key])*inverse);
assert.equal('mode' in returned.shared_capex.optimizer_installation_wdc,false);
const again=technoeconomicCostYearAdjustedDraft(returned,returned.cost_year_basis,2022,catalog);
close(again.shared_capex.optimizer_unit_price_usd,40);
close(again.shared_capex.optimizer_installation_wdc.sd,.002);
console.log(JSON.stringify({passed:true}));
""")

    def test_nonshared_distributions_and_preserved_committed_year(self):
        self.run_node(r"""
fresh.shared_capex=null;
fresh.cost_year='2024';
fresh.systems.solectria.cost_lines=[{key:'Capex',distribution:{family:'triangular',low:'1',mode:'2',high:'3'},occurrence_years:''},{key:'Om',distribution:{family:'fixed',value:'12'},occurrence_years:''},{key:'Replacement',distribution:{family:'uniform',low:'.1',high:'.2'},occurrence_years:'15'}];
fresh.systems.solectria.replacement_enabled=true;
const old={source_year:2024,applied_year:2024,factor:1,original_costs:technoeconomicCostYearMoney(fresh)};
const adjusted=technoeconomicCostYearAdjustedDraft(fresh,old,2022,catalog);
const factor=catalog.years['2022'].value/catalog.years['2024'].value;
close(adjusted.systems.solectria.cost_lines[0].distribution.mode,2*factor);
close(adjusted.systems.solectria.cost_lines[1].distribution.value,12*factor);
close(adjusted.systems.solectria.cost_lines[2].distribution.high,.2*factor);
assert.equal(adjusted.systems.solectria.cost_lines[2].occurrence_years,'15');
technoeconomicCostYearBasis=adjusted.cost_year_basis;
technoeconomicElements={standaloneCostYear:{value:'2030'}};
assert.equal(technoeconomicCostYearAppliedYear(),'2022');
assert.equal(technoeconomicCostYearHasPendingChange(),true);
const stored=technoeconomicStandaloneSanitizeDraft(JSON.parse(JSON.stringify(adjusted)));
assert.equal(stored.cost_year,'2022');
assert.deepEqual(stored.cost_year_basis,adjusted.cost_year_basis);
console.log(JSON.stringify({passed:true}));
""")

    def test_canonical_receipt_matches_backend_at_current_capacity_ratio(self):
        result = self.run_node(r"""
const adjusted=technoeconomicCostYearAdjustedDraft(fresh,basis,2022,catalog);
technoeconomicCostYearBasis=adjusted.cost_year_basis;
const factor=adjusted.cost_year_basis.factor;
const payload={finance:{constant_dollar_cost_year:2022},paired_commercial:{
  shared_initial_capex:{
    common_capex_wdc:{family:'uniform',low:1.07*factor,high:1.17*factor},
    optimizer_installation_wdc:{family:'uniform',low:.004*factor,high:.010*factor},
    optimizer_unit_price_usd:37.75*factor,
    report_context:{component_allocations:[{midpoint_wdc:.27*factor,low_wdc:.26*factor,high_wdc:.28*factor}]}
  },systems:['solectria','solaredge'].map(technology=>({technology,cost_lines:[
    {input_id:technology+'.annual-om',constant_dollar_cost_year:2022,distribution:{family:'uniform',low:8/1000*1.45*factor,high:13/1000*1.45*factor}},
    {input_id:technology+'.full-capex',constant_dollar_cost_year:2022,distribution:{family:'uniform',low:1.07*1.45*factor,high:1.17*1.45*factor}}
  ]}))}};
payload.cost_year_adjustment=technoeconomicCostYearReceipt(payload);
close(payload.cost_year_adjustment.original_money['paired_commercial.systems.solectria.cost_lines.solectria.annual-om.distribution'].low,8/1000*1.45);
console.log(JSON.stringify(payload));
""")
        receipt = technoeconomic_cost_year.validate_cost_year_adjustment(result)
        self.assertEqual(2026, receipt['source_year'])
        self.assertEqual(2022, receipt['target_year'])
        self.assertTrue(receipt['source_provisional'])

    def test_year_input_previews_without_waiting_for_change_or_blur(self):
        self.run_node(r"""
(async()=>{
const handlers={};
const year={value:'2022'};
const nodes={
  technoeconomicCostYearPreview:{hidden:true},
  technoeconomicCostYearStatus:{textContent:''},
  technoeconomicCostYearApply:{disabled:true},
  technoeconomicCostYearTable:{children:[],replaceChildren(){this.children=[];},append(child){this.children.push(child);}}
};
technoeconomicNode=(tag,options={})=>({tag,textContent:options.text||'',children:[],append(child){this.children.push(child);}});
technoeconomicDomElement=(id)=>nodes[id]||null;
technoeconomicElements={standaloneCostYear:year,form:{addEventListener:(kind,callback)=>handlers[kind]=callback}};
technoeconomicCostYearBasis=basis;
technoeconomicCostYearCatalog=catalog;
technoeconomicStandaloneDraftSnapshot=()=>fresh;
technoeconomicClearStandaloneAcceptance=()=>false;
technoeconomicMarkDraftChanged=()=>{};
const source=require('node:fs').readFileSync('frontend/js/06-technoeconomic.js','utf8');
const start=source.indexOf("technoeconomicElements.form.addEventListener('input',");
const end=source.indexOf("technoeconomicElements.form.addEventListener('change',",start);
eval(source.slice(start,end));
handlers.input({target:year});
await new Promise(resolve=>setImmediate(resolve));
assert.equal(technoeconomicCostYearPreview.cost_year,'2022');
assert.equal(nodes.technoeconomicCostYearApply.disabled,false);
assert.match(nodes.technoeconomicCostYearStatus.textContent,/118\.02 \/ 133\.86 = 0\.88/);
const installation=nodes.technoeconomicCostYearTable.children[0].children.find(row=>row.children[0]?.textContent==='Optimizer installation (USD/kWdc)');
assert.equal(installation.children[1].textContent,'Uniform 4.00 to 10.00');
assert.equal(installation.children[2].textContent,'Uniform 3.53 to 8.82');
assert.equal(fresh.cost_year,'2026');
assert.equal(fresh.shared_capex.optimizer_unit_price_usd,'37.75');
year.value='202';handlers.input({target:year});
assert.equal(nodes.technoeconomicCostYearApply.disabled,true);
assert.equal(technoeconomicCostYearPreview,null);
year.value='2030';handlers.input({target:year});
await new Promise(resolve=>setImmediate(resolve));
assert.equal(nodes.technoeconomicCostYearApply.disabled,true);
assert.match(nodes.technoeconomicCostYearStatus.textContent,/No recorded GDP deflator/);
console.log(JSON.stringify({passed:true}));
})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_two_decimal_money_inputs_preserve_values_until_explicit_edit(self):
        self.run_node(r"""
const input={dataset:{},value:''};
const factor=catalog.years['2022'].value/catalog.years['2026'].value;
const installation=String(.004*factor);
technoeconomicSetMoneyInput(input,installation,1000);
assert.equal(input.value,'3.53');
assert.equal(technoeconomicReadMoneyInput(input),installation);
technoeconomicMoneyInputEdited(input,true);
assert.equal(technoeconomicReadMoneyInput(input),installation);
const container={querySelectorAll:()=>[Object.assign(input,{dataset:{...input.dataset,teaV4Param:'low'}})]};
assert.equal(technoeconomicStandaloneReadParameterValues(container).low,installation);
technoeconomicMoneyInputEdited(input);
close(technoeconomicReadMoneyInput(input),.00353);
input.value='4.126';
technoeconomicMoneyInputEdited(input,true);
assert.equal(input.value,'4.13');
close(technoeconomicReadMoneyInput(input),.004126);
const price=String(37.75*factor);
technoeconomicSetMoneyInput(input,price);
assert.equal(input.value,'33.29');
assert.equal(technoeconomicReadMoneyInput(input),price);
input.value='40';
technoeconomicMoneyInputEdited(input);
assert.equal(technoeconomicReadMoneyInput(input),'40');
technoeconomicMoneyInputEdited(input,true);
assert.equal(input.value,'40.00');
assert.equal(technoeconomicReadMoneyInput(input),'40');
assert.equal(technoeconomicFormatNumber(1234.5678,6),'1,234.57');
assert.equal(technoeconomicFormatNumber(1200,0),'1,200');
assert.equal(technoeconomicStandaloneCostReview({unit:'constant_usd_per_target_w',timing:'initial_t0',distribution:{family:'fixed',value:.004}},'ac_operating_limit',2026),'real 2026 USD/kWac; Fixed 4.00');
console.log(JSON.stringify({passed:true}));
""")


if __name__ == '__main__':
    unittest.main()
