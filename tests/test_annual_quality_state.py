import json
from pathlib import Path
import shutil
import subprocess
import unittest


class AnnualQualityStateTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute dashboard behavior')
    def test_only_completed_evidence_can_show_complete(self):
        source = (Path(__file__).parents[1] / 'frontend/js/05-calibration-factors.js').read_text(encoding='utf-8')
        function = source[source.index('        function renderAnnualQuality('):]
        harness = r'''
const elements = Object.fromEntries(['annualQualityPanel', 'annualStatQuality'].map(id => [id, {
    textContent: '', innerHTML: '', classes: new Set(),
    classList: {toggle(name, enabled) {enabled ? elements[id].classes.add(name) : elements[id].classes.delete(name)},
                remove(...names) {names.forEach(name => elements[id].classes.delete(name))}}
}]));
const document = {getElementById: id => elements[id]};
const escapeHtml = text => text.replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const states = [];
for (const state of ['empty','queued','running','failed','cancelled','missing','done']) {
    renderAnnualQuality([], state);
    states.push({state, label: elements.annualStatQuality.textContent,
                 positive: elements.annualStatQuality.classes.has('positive')});
}
renderAnnualQuality(['<partial year>'], 'done');
console.log(JSON.stringify({states, warning: elements.annualStatQuality.textContent,
                           html: elements.annualQualityPanel.innerHTML}));
'''
        result = subprocess.run(['node', '-e', function + harness], capture_output=True, text=True, check=True)
        evidence = json.loads(result.stdout)
        for row in evidence['states']:
            self.assertEqual(row['state'] == 'done', row['positive'])
            self.assertEqual(row['state'] == 'done', row['label'] == 'Complete')
        self.assertEqual('1 warning', evidence['warning'])
        self.assertIn('&lt;partial year&gt;', evidence['html'])
