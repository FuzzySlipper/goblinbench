import importlib.util
from pathlib import Path

import yaml


spec = importlib.util.spec_from_file_location(
    'dsh_compare', Path(__file__).parents[1] / 'scripts/dsh-compare.py')
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def test_cordis_yaml_preserves_off_effort_and_expressions(tmp_path):
    source = tmp_path / 'config.yml'
    source.write_text('disabled: false\ncondition: !!js process.platform === "win32"\n'
                      'reasoningEfforts: {off: null, high: ultra, max: max}\n')
    value = comparison.read_yaml(source)
    assert value['disabled'] is False
    assert value['reasoningEfforts'] == {'off': None, 'high': 'ultra', 'max': 'max'}
    assert isinstance(value['condition'], comparison.Js)
    comparison.write_yaml(source, value)
    assert comparison.read_yaml(source) == value
    assert '!!js' in source.read_text()


def test_profile_keeps_standard_groups_and_only_requested_web_settings(tmp_path):
    bundle = tmp_path / 'packages/bundle'
    (bundle / 'base').mkdir(parents=True)
    (bundle / 'web-app/presets').mkdir(parents=True)
    comparison.write_yaml(bundle / 'base/cordis.patch.yml', [{'insert': [
        {'id': 'system-prompt'}, {'id': 'tool-subagent'}, {'id': 'tool-fs'}]}])
    comparison.write_yaml(bundle / 'web-app/cordis.patch.yml', [
        {'id': 'tool-subagent', 'disabled': True}, {'id': 'tool-fs', 'disabled': True}])
    group = {'id': 'delegation', 'name': 'cordis:group', 'group': True,
             'isolate': {'workflowEngine': True}, 'config': [
                 {'id': 'tool-subagent', 'config': {
                     'modelSelectionSettings': True, 'backgroundMode': 'continuable'}}]}
    comparison.write_yaml(bundle / 'web-app/presets/standard.patch.yml', [{'insert': [
        {'config': {'plugins': [
            {'id': 'persona', 'config': {'prefix': 'Coding agent', 'suffix': 'Workspace'}},
            {'id': 'tool-fs', 'name': 'fs'}, group]}}]}])
    providers = {'id': 'llm-pi-ai', 'config': {'providers': {'sample': {
        'models': [{'id': 'm', 'reasoningEfforts': {'high': 'ultra'}}]}}}}
    patch = comparison.standard_patch(tmp_path, [providers, {'id': 'ui-theme'}])
    assert providers in patch
    assert not any(row.get('id') == 'ui-theme' for row in patch)
    assert {'id': 'tool-subagent', 'disabled': True} in patch
    fs = next(row for row in patch if row.get('name') == 'fs')
    assert fs['disabled'] is False
    actual = next(row['insert'][0] for row in patch if row.get('insert'))
    assert actual['isolate'] == {'workflowEngine': True}
    assert actual['config'][0]['config'] == {'backgroundMode': 'continuable'}
    assert group['config'][0]['config']['modelSelectionSettings'] is True
