import asyncio
import json
from types import SimpleNamespace

from src.workflow.definition import WorkflowNode
from src.workflow.nodes.agent import AgentNode
from src.workflow.nodes.base import NodeContext, NodeResult
from src.workflow.nodes.rewrite_progress import RewriteProgress


def test_writer_retry_skips_completed_rows_and_reopens_only_rejected_unit(tmp_path):
    paragraphs = [{"id":f"p{i:04}", "text":f"请把第{i}盏灯熄了。"} for i in range(1, 5)]
    units = [{"id":p["id"]+"-s1","paragraph_id":p["id"],"old":p["text"],"occurrence":1} for p in paragraphs[:3]]
    view = {"source_sha256":"a"*64,"source_body":{"paragraphs":paragraphs},
            "zhuque_review":{"rewrite_units":units,"reference_paragraphs":["p0004"]}}
    (tmp_path/"in.json").write_text(json.dumps(view),encoding="utf8")
    node = WorkflowNode(id="writer",agent_type="writer",model_override="lingsuan-google:gemini-4-neon",
                        node_params={"resumable_rewrite_input":"editor"}, output_variable="patch",
                        output_file_path="out.json",save_output_to_file=True)
    state = SimpleNamespace(session_id="",rejection_history=[])
    ctx = NodeContext(definition=SimpleNamespace(variables=[]),node_def=node,node_state=state,
                      shared_ws=tmp_path,task_id="test",parameter_values={"editor":"in.json"})
    calls = []
    class Writer(AgentNode):
        async def execute(self, ctx):
            if ctx.node_def.node_params.get("resumable_rewrite_input"):
                return await super().execute(ctx)
            item = json.loads(ctx.node_def.first_message.split("\n",1)[1])["片段"]
            key = item["id"]
            calls.append(key)
            if key == "p0002-s1" and calls.count(key)==1:
                return NodeResult(status="failed",error="peer closed")
            data = {"id":key,"reference_id":"p0004","replacement":"烦你熄一下第"+key+"盏灯。"+str(calls.count(key))}
            return NodeResult(status="completed",outputs={"patch":json.dumps(data)})
    writer = Writer()
    run = lambda: asyncio.run(writer.execute(ctx))
    assert run().status == "failed" and not (tmp_path/"out.json").exists()
    assert run().status == "completed"
    first = json.loads((tmp_path/"out.json").read_text())["rewrites"]
    assert calls == [u["id"] for u in units]+["p0002-s1"]
    assert run().status == "completed" and len(calls)==4
    state.rejection_history.append({"rejection_id":"r1","reason":"p0003-s1 称呼有误"})
    assert run().status == "completed" and calls[4:]==["p0003-s1"]
    second = json.loads((tmp_path/"out.json").read_text())["rewrites"]
    assert second[:2]==first[:2] and second[2]!=first[2]
    assert run().status == "completed" and len(calls)==5
    progress = RewriteProgress(tmp_path/"rewrite-progress.sqlite3",view,["different model"])
    assert progress.rows()=={}

