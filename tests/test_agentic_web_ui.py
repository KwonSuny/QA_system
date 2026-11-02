"""检查来源卡片与通识标记的前端行为，不引入浏览器或 npm 依赖。"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


class SourceUITests(unittest.TestCase):
    def test_history_reload_preserves_origins_and_unbound_smart_mode(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js 不可用')
        source = (Path(__file__).resolve().parents[1]/'app'/'static'/'app.js').read_text(encoding='utf-8-sig')
        functions = '\n'.join(re.search(r'(?:async )?function '+name+r'\([^\n]*\) \{[\s\S]*?\n\}', source).group()
                              for name in ['selectConversation', 'updateSourceMode'])
        program = r'''
const assert=require('node:assert/strict');
const state={kbs:[],messages:[]};
const elements={};
function $(id) { return elements[id] || (elements[id]={value:'',textContent:'',checked:false,disabled:false}); }
const metadata={source_mode:'smart',answer_sources:['model'],warnings:['已关闭联网']};
async function request() { return {conversation:{id:'c',kb_id:'',messages:[{role:'assistant',content:'通识解释',chunks:[],metadata}]}}; }
function renderKbList() {} function renderConvList() {} function renderMessages() {}
function toast(message) { throw new Error(message); }
eval(FUNCTIONS);
(async()=>{
  await selectConversation('c');
  assert.deepEqual(state.messages[0].metadata,metadata);
  assert.equal($('source-mode').value,'smart');
  assert.equal($('allow-web').checked,false);
  assert.equal($('allow-web').disabled,false);
  assert.equal($('active-kb-name').textContent,'通用与联网问答');
  assert.equal($('active-kb-meta').textContent,'此会话未绑定知识库');
})().catch(error=>{console.error(error);process.exitCode=1});
'''.replace('FUNCTIONS', json.dumps(functions))
        result = subprocess.run([node, '-e', program], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_references_use_safe_links_and_general_answers_have_no_source_cards(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js 不可用')
        source = (Path(__file__).resolve().parents[1]/'app'/'static'/'app.js').read_text(encoding='utf-8-sig')
        names = ['escapeHtml', 'appendSources', 'appendSourceGroup', 'safeSourceUrl', 'appendAnswerMetadata', 'appendSearchResults']
        functions = '\n'.join(re.search(r'function '+name+r'\([^\n]*\) \{[\s\S]*?\n\}', source).group() for name in names)
        program = r'''
const assert = require('node:assert/strict');
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.textContent=''; this.innerHTML=''; this.className=''; }
  appendChild(child) { this.children.push(child); }
  addEventListener() {}
}
global.document={createElement:tag=>new Element(tag)};
eval(FUNCTIONS);
assert.equal(safeSourceUrl('javascript:alert(1)'), false);
assert.equal(safeSourceUrl('https://name:pass@example.org'), false);
const root=new Element('main');
appendSources(root,[{source_type:'kb',evidence_id:'K1',text:'KB正文',score:0.8},
 {source_type:'web',evidence_id:'W1',text:'网页正文',content_kind:'search_excerpt',url:'https://example.org/"x',retrieved_at:'2026-10-20'},
 {source_type:'web',evidence_id:'W2',text:'另一网页正文',url:'javascript:alert(1)'}]);
assert.equal(root.children.length,2);
assert.match(root.children[0].children[0].textContent,/知识库/);
assert.match(root.children[1].children[0].textContent,/网页/);
const pages=root.children[1].children[1].children;
assert.equal(pages[0].children[0].tag,'a');
assert.equal(pages[0].children[0].rel,'noopener noreferrer');
assert.match(pages[0].innerHTML,/搜索摘录/);
assert.equal(pages[1].children.length,0);
const general=new Element('main');
appendSources(general,[]);
appendAnswerMetadata(general,{source_mode:'smart',answer_sources:['model'],warnings:[]});
assert.equal(general.children.length,1);
assert.equal(general.children[0].className,'answer-origin');
assert.match(general.children[0].textContent,/未经外部资料核验/);
const failure=new Element('main');
appendAnswerMetadata(failure,{source_mode:'smart',answer_sources:[],show_search_results:true,
 search_results:[{title:'<script>bad</script>',text:'未核验摘录',url:'javascript:alert(1)',content_kind:'search_excerpt'}]});
assert.match(failure.children[1].children[0].textContent,/未作为答案依据/);
const resultItem=failure.children[1].children[1].children[0];
assert.match(resultItem.innerHTML,/&lt;script&gt;/);
assert.equal(resultItem.children.length,0);
'''.replace('FUNCTIONS', json.dumps(functions))
        result = subprocess.run([node, '-e', program], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_literal_element_references_exist(self):
        root = Path(__file__).resolve().parents[1]/'app'/'static'
        js = (root/'app.js').read_text(encoding='utf-8-sig')
        html = (root/'index.html').read_text(encoding='utf-8-sig')
        refs = set(re.findall(r"\$\('([^']+)'\)", js))
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)), 'HTML id 重复')
        self.assertEqual(refs-set(ids), set())
